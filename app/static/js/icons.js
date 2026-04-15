(function () {
  const base = {
    add: "M12 5v14M5 12h14",
    add_card: "M3 7h18v10H3zM3 10h18M7 15h4M17 13v4M15 15h4",
    add_circle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 8v8M8 12h8",
    add_task: "M4 12l4 4L20 5M12 19h7",
    all_inclusive: "M7 8c-3 0-5 2-5 4s2 4 5 4c4 0 6-8 10-8 3 0 5 2 5 4s-2 4-5 4c-4 0-6-8-10-8z",
    analytics: "M4 19V5M10 19V9M16 19v-7M22 19H2",
    archive: "M4 7h16M5 7l1 13h12l1-13M8 3h8l2 4H6l2-4zM10 12h4",
    arrow_back: "M19 12H5M12 5l-7 7 7 7",
    arrow_forward: "M5 12h14M12 5l7 7-7 7",
    bar_chart: "M4 19V9M10 19V5M16 19v-8M22 19H2",
    build: "M14.7 6.3a4 4 0 0 1-5 5L4 17l3 3 5.7-5.7a4 4 0 0 1 5-5L15 12l-3-3 2.7-2.7z",
    build_circle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM14.5 8.5l-6 6 2 2 6-6",
    calendar_month: "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4M8 13h2M12 13h2M16 13h2M8 17h2M12 17h2",
    calendar_today: "M5 5h14v14H5zM5 9h14M8 3v4M16 3v4",
    chair: "M7 12V6a5 5 0 0 1 10 0v6M5 12h14v8M8 20v-4M16 20v-4",
    check: "M4 12l5 5L20 6",
    check_circle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 12l3 3 5-6",
    chevron_right: "M9 5l7 7-7 7",
    close: "M6 6l12 12M18 6L6 18",
    dark_mode: "M21 14.5A8 8 0 0 1 9.5 3 9 9 0 1 0 21 14.5z",
    delete: "M5 7h14M9 7V5h6v2M8 7l1 13h6l1-13",
    description: "M6 3h9l3 3v15H6zM14 3v4h4M9 11h6M9 15h6M9 19h4",
    devices: "M3 5h14v10H3zM7 19h6M10 15v4M18 10h3v9h-3z",
    directions_car: "M5 14h14l-2-6H7l-2 6zM6 14v4M18 14v4M7 18h2M15 18h2",
    donut_large: "M12 21a9 9 0 1 0-9-9h5a4 4 0 1 1 4 4zM3 12a9 9 0 0 1 9-9v5a4 4 0 0 0-4 4z",
    download: "M12 3v11M7 9l5 5 5-5M5 21h14",
    edit: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
    error: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v6M12 17h.01",
    event_repeat: "M5 5h14v14H5zM5 9h14M8 3v4M16 3v4M8 14h8M13 11l3 3-3 3",
    expand_more: "M6 9l6 6 6-6",
    filter_alt: "M4 5h16l-6 7v6l-4 2v-8z",
    filter_alt_off: "M4 5h16l-5 6M10 13v5l4-2v-1M3 3l18 18",
    folder_open: "M3 7h7l2 2h9l-2 10H3zM3 7v12",
    history: "M4 12a8 8 0 1 0 3-6M4 4v5h5M12 8v5l4 2",
    home_repair_service: "M4 10h16v9H4zM8 10V7h8v3M9 14h6",
    home_storage: "M3 10l9-7 9 7v10H3zM8 20v-6h8v6",
    image: "M4 5h16v14H4zM8 13l3 3 3-4 4 5M8 9h.01",
    inventory_2: "M4 7l8-4 8 4-8 4zM4 7v10l8 4 8-4V7M12 11v10",
    kitchen: "M7 3h10v18H7zM10 6h4M15 12h.01",
    light_mode: "M12 5V3M12 21v-2M5 12H3M21 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M17.7 6.3l1.4-1.4M4.9 19.1l1.4-1.4M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    local_gas_station: "M6 3h8v18H6zM8 7h4M14 8h3l2 2v7a2 2 0 0 1-4 0v-4h-1",
    location_on: "M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11zM12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
    login: "M10 17l5-5-5-5M15 12H3M17 5h4v14h-4",
    mail: "M4 6h16v12H4zM4 7l8 6 8-6",
    menu: "M4 7h16M4 12h16M4 17h16",
    menu_book: "M4 5h7a3 3 0 0 1 3 3v12a3 3 0 0 0-3-3H4zM20 5h-7a3 3 0 0 0-3 3",
    open_in_new: "M14 4h6v6M20 4l-9 9M18 13v7H4V6h7",
    outgoing_mail: "M4 6h16v12H4zM4 7l8 6 4-3M16 8h5M19 5l3 3-3 3",
    payments: "M3 7h18v10H3zM3 10h18M7 15h4",
    receipt_long: "M6 3l2 1 2-1 2 1 2-1 2 1 2-1v18l-2-1-2 1-2-1-2 1-2-1-2 1zM9 8h6M9 12h6M9 16h4",
    request_quote: "M6 3h12v18H6zM9 8h6M9 12h6M11 16h2",
    save: "M5 4h12l2 2v14H5zM8 4v6h8M8 20v-6h8",
    search: "M10 18a8 8 0 1 1 5.7-2.3L21 21",
    search_off: "M10 18a8 8 0 0 1-6.3-12.9M14 14a8 8 0 0 0-9-9M3 3l18 18",
    settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 12h2M18 12h2M12 4v2M12 18v2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M17.7 6.3l-1.4 1.4M7.7 16.3l-1.4 1.4",
    space_dashboard: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
    stacked_bar_chart: "M4 19V9M9 19V5M14 19v-7M19 19V8M22 19H2",
    summarize: "M6 3h12v18H6zM9 8h6M9 12h6M9 16h4",
    upload_file: "M12 16V5M7 10l5-5 5 5M5 21h14",
    verified_user: "M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6zM8 12l3 3 5-6",
    waving_hand: "M7 11V5a2 2 0 0 1 4 0v5M11 10V4a2 2 0 0 1 4 0v7M15 11V6a2 2 0 0 1 4 0v8c0 4-3 7-7 7h-1a7 7 0 0 1-7-7v-3a2 2 0 0 1 3 0z"
  };

  const aliases = {
    photo: "image"
  };

  function normalizeName(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  function svgFor(name) {
    const key = aliases[name] || name;
    const path = base[key] || "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 8v5M12 16h.01";
    return (
      '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      `<path d="${path}"></path></svg>`
    );
  }

  function renderIcon(element) {
    if (element.dataset.hbIconRendered === "true") {
      return;
    }
    const name = normalizeName(element.textContent);
    element.dataset.icon = name;
    element.dataset.hbIconRendered = "true";
    element.setAttribute("aria-hidden", "true");
    element.innerHTML = svgFor(name);
    element.classList.add("hb-icon-ready");
  }

  function renderIcons(root) {
    const scope = root || document;
    scope.querySelectorAll(".material-symbols-outlined").forEach(renderIcon);
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderIcons(document);
    const observer = new MutationObserver(function (mutations) {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.classList.contains("material-symbols-outlined")) {
              renderIcon(node);
            } else {
              renderIcons(node);
            }
          }
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });

  window.renderHomeBaseIcons = renderIcons;
})();
