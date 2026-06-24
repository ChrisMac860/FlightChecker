/* ============================================================
   Eitiltí Saora — client-side deal rendering
   Plain ES6, no dependencies.

   SECURITY NOTE: all deal data ultimately originates from
   third-party fare APIs and parsed emails, so it is treated as
   UNTRUSTED. We never build markup from deal values via
   innerHTML. Every dynamic value reaches the DOM only through
   document.createElement + textContent (or setAttribute on a
   strictly-validated href). This eliminates HTML-injection /
   XSS sinks.
   ============================================================ */

(function () {
  "use strict";

  // ---- Module state ---------------------------------------------------
  var allDeals = [];      // full list loaded from deals.json
  var generatedAt = null; // ISO timestamp string for the dataset

  // ---- Element references (static structural elements only) -----------
  var els = {
    search: document.getElementById("search"),
    origin: document.getElementById("origin"),
    source: document.getElementById("source"),
    maxprice: document.getElementById("maxprice"),
    sort: document.getElementById("sort"),
    direct: document.getElementById("direct"),
    list: document.getElementById("deals"),
    empty: document.getElementById("empty"),
    statusCount: document.getElementById("status-count"),
    statusUpdated: document.getElementById("status-updated")
  };

  // ====================================================================
  //  Helpers
  // ====================================================================

  /**
   * Human "found …" label derived from an ISO timestamp, relative to now.
   * e.g. "found today", "found 2 days ago".
   */
  function relativeFound(iso) {
    var then = Date.parse(iso);
    if (isNaN(then)) {
      return "";
    }
    var diffMs = Date.now() - then;
    var dayMs = 86400000;
    var days = Math.floor(diffMs / dayMs);

    if (days <= 0) {
      // Same calendar-ish window — within ~24h
      var hours = Math.floor(diffMs / 3600000);
      if (hours <= 0) {
        return "found just now";
      }
      if (hours === 1) {
        return "found 1 hour ago";
      }
      if (hours < 24) {
        return "found " + hours + " hours ago";
      }
      return "found today";
    }
    if (days === 1) {
      return "found yesterday";
    }
    if (days < 30) {
      return "found " + days + " days ago";
    }
    var months = Math.floor(days / 30);
    return months === 1 ? "found 1 month ago" : "found " + months + " months ago";
  }

  /**
   * Friendly "Updated …" label for the generated_at timestamp.
   * Shows a relative phrase plus an absolute local date for clarity.
   */
  function updatedLabel(iso) {
    var when = Date.parse(iso);
    if (isNaN(when)) {
      return "";
    }
    var rel = relativeFound(iso).replace(/^found /, "");
    if (!rel) {
      rel = "recently";
    }
    var d = new Date(when);
    // Absolute, locale-aware, compact.
    var abs = d.toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit"
    });
    return "Updated " + rel + " · " + abs;
  }

  /**
   * Only allow http(s) URLs to become a clickable link. Anything else
   * (empty string, javascript:, data:, etc.) yields null so no link
   * is rendered. Defensive parsing — never trust source data.
   */
  function safeHttpUrl(raw) {
    if (typeof raw !== "string" || raw.trim() === "") {
      return null;
    }
    var parsed;
    try {
      parsed = new URL(raw, window.location.href);
    } catch (e) {
      return null;
    }
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
    return null;
  }

  /** Debounce: collapse rapid calls (e.g. keystrokes) into one. */
  function debounce(fn, ms) {
    var timer;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, ms);
    };
  }

  /** Small convenience: make an element with a class + text. */
  function makeEl(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  // ====================================================================
  //  Filtering & sorting
  // ====================================================================

  function applyControls() {
    var q = (els.search.value || "").trim().toLowerCase();
    var origin = els.origin.value;
    var source = els.source.value;
    var maxPrice = els.maxprice.value; // "25" | "50" | "75" | "100" | "any"
    var directOnly = els.direct.checked;
    var sortMode = els.sort.value;

    var filtered = allDeals.filter(function (d) {
      // Free-text search across the key human fields.
      if (q) {
        var haystack = [
          d.destination,
          d.destination_code,
          d.origin,
          d.origin_city,
          d.route,
          d.airline
        ]
          .join(" ")
          .toLowerCase();
        if (haystack.indexOf(q) === -1) {
          return false;
        }
      }

      // Origin filter (DUB / BFS).
      if (origin !== "all" && d.origin !== origin) {
        return false;
      }

      // Source filter (ryanair / aviasales / gmail).
      if (source !== "all" && d.source !== source) {
        return false;
      }

      // Max price in EUR (normalised value).
      if (maxPrice !== "any") {
        var cap = parseFloat(maxPrice);
        if (priceEur(d) > cap) {
          return false;
        }
      }

      // Direct-only.
      if (directOnly && d.stops !== "Non-stop") {
        return false;
      }

      return true;
    });

    sortDeals(filtered, sortMode);
    render(filtered);
    updateStatus(filtered.length);
  }

  // A deal's EUR price for ranking/filtering. A missing, non-numeric or
  // non-positive value is treated as "unknown" (Infinity) so such deals are
  // excluded by a max-price cap and sorted last instead of masquerading as €0.
  function priceEur(d) {
    return typeof d.price_eur === "number" && d.price_eur > 0 ? d.price_eur : Infinity;
  }

  function sortDeals(list, mode) {
    if (mode === "soonest") {
      // Earliest departure first.
      list.sort(function (a, b) {
        return String(a.depart_date).localeCompare(String(b.depart_date));
      });
    } else if (mode === "recent") {
      // Most recently seen first.
      list.sort(function (a, b) {
        return (Date.parse(b.last_seen) || 0) - (Date.parse(a.last_seen) || 0);
      });
    } else {
      // Default: cheapest by normalised EUR value, ascending.
      list.sort(function (a, b) {
        return priceEur(a) - priceEur(b);
      });
    }
  }

  // ====================================================================
  //  Rendering (DOM-only, no innerHTML with data)
  // ====================================================================

  function buildBadge(text) {
    return makeEl("span", "badge", text);
  }

  function buildDealItem(d) {
    var li = makeEl("li", "deal");
    var article = makeEl("article");
    li.appendChild(article);

    // --- Main column ---
    var main = makeEl("div", "deal__main");

    // Route, e.g. "DUB → BCN"
    main.appendChild(makeEl("h2", "deal__route", d.route || ""));

    // Sub line: destination city + dates.
    var subBits = [];
    if (d.destination) {
      subBits.push(d.destination);
    }
    if (d.dates_label) {
      subBits.push(d.dates_label);
    }
    main.appendChild(makeEl("p", "deal__sub", subBits.join(" · ")));

    // Badges: nights / days off / stops / source.
    var badges = makeEl("div", "deal__badges");

    if (typeof d.nights === "number") {
      badges.appendChild(
        buildBadge(d.nights + (d.nights === 1 ? " night" : " nights"))
      );
    }
    if (typeof d.days_off === "number") {
      var off =
        d.days_off === 0
          ? "no days off"
          : d.days_off + (d.days_off === 1 ? " day off" : " days off");
      badges.appendChild(buildBadge(off));
    }
    if (d.stops) {
      badges.appendChild(buildBadge(d.stops));
    }
    if (d.source) {
      badges.appendChild(buildBadge(sourceLabel(d.source)));
    }
    main.appendChild(badges);

    // "found …" relative label.
    var found = relativeFound(d.last_seen);
    if (found) {
      main.appendChild(makeEl("p", "deal__found", found));
    }

    article.appendChild(main);

    // --- Aside column: price + view link ---
    var aside = makeEl("div", "deal__aside");

    // Native price string (e.g. "EUR 45.00" / "GBP 24.99").
    aside.appendChild(makeEl("div", "deal__price", d.price || ""));

    // "View" link only when we have a safe http(s) url.
    var href = safeHttpUrl(d.url);
    if (href) {
      var link = makeEl("a", "deal__view", "View →");
      link.setAttribute("href", href);
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
      // Accessible label describing where it goes.
      link.setAttribute(
        "aria-label",
        "View deal " + (d.route || "") + " for " + (d.price || "")
      );
      aside.appendChild(link);
    }

    article.appendChild(aside);
    return li;
  }

  function sourceLabel(source) {
    switch (source) {
      case "ryanair":
        return "Ryanair";
      case "aviasales":
        return "Aviasales";
      case "gmail":
        return "Email";
      default:
        return String(source);
    }
  }

  function render(list) {
    // Clear previous results without innerHTML.
    while (els.list.firstChild) {
      els.list.removeChild(els.list.firstChild);
    }

    if (!list.length) {
      showEmpty(
        "No matching deals",
        "Try widening your filters or clearing the search."
      );
      return;
    }

    hideEmpty();

    // Batch DOM writes via a fragment.
    var frag = document.createDocumentFragment();
    list.forEach(function (d) {
      frag.appendChild(buildDealItem(d));
    });
    els.list.appendChild(frag);
  }

  // ====================================================================
  //  Status line + empty/error states
  // ====================================================================

  function updateStatus(count) {
    var noun = count === 1 ? "deal" : "deals";
    els.statusCount.textContent = count + " " + noun;
    els.statusUpdated.textContent = generatedAt ? updatedLabel(generatedAt) : "";
  }

  function showEmpty(title, text) {
    // Build the empty/error block with DOM nodes (static copy only).
    while (els.empty.firstChild) {
      els.empty.removeChild(els.empty.firstChild);
    }
    els.empty.appendChild(makeEl("p", "empty__title", title));
    els.empty.appendChild(makeEl("p", "empty__text", text));
    els.empty.hidden = false;
  }

  function hideEmpty() {
    els.empty.hidden = true;
  }

  // ====================================================================
  //  Wiring
  // ====================================================================

  function attachListeners() {
    // 'input' for live search (debounced to avoid re-rendering on every
    // keystroke); 'change' for selects/checkbox.
    els.search.addEventListener("input", debounce(applyControls, 120));
    els.origin.addEventListener("change", applyControls);
    els.source.addEventListener("change", applyControls);
    els.maxprice.addEventListener("change", applyControls);
    els.sort.addEventListener("change", applyControls);
    els.direct.addEventListener("change", applyControls);
  }

  function init() {
    attachListeners();

    // 'no-cache' revalidates (cheap 304 when unchanged) so repeat visits don't
    // re-download the whole file, while still picking up updates promptly.
    fetch("./deals.json", { cache: "no-cache" })
      .then(function (res) {
        if (!res.ok) {
          throw new Error("HTTP " + res.status);
        }
        return res.json();
      })
      .then(function (data) {
        allDeals = Array.isArray(data && data.deals) ? data.deals : [];
        generatedAt = data && data.generated_at ? data.generated_at : null;
        applyControls();
      })
      .catch(function (err) {
        // Friendly, non-throwing error state.
        // (Logged for developers; not surfaced as a raw exception.)
        if (window.console && console.warn) {
          console.warn("Could not load deals.json:", err);
        }
        els.statusCount.textContent = "";
        els.statusUpdated.textContent = "";
        showEmpty(
          "Couldn't load deals right now",
          "The deals file is unavailable. Please refresh in a little while."
        );
      });
  }

  // The script is loaded with `defer`, so the DOM is ready here.
  init();
})();
