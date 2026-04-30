/* grid_sort.js — universal click-to-sort for any <table> with a <thead>.
 *
 * Auto-attaches to every table inside <main> on page load. Re-attaches
 * to tables swapped in by HTMX. Idempotent: a table already wired won't
 * be rewired.
 *
 * Per-column opt-out:    <th data-no-sort="true">Actions</th>
 * Per-table opt-out:     <table data-no-sort="true"> ... </table>
 * Per-cell explicit val: <td data-sort-value="2026-04-29T14:30">29 Apr</td>
 *
 * Type detection samples up to 20 non-empty cells and picks number /
 * date / string. Numbers strip $ , % whitespace. Dates use Date.parse.
 *
 * State persisted in localStorage keyed by ``<pathname>::<table-index>``
 * so reloading the same page restores the last sort.
 */
(function () {
  const STORAGE_PREFIX = "grid-sort:";
  const SAMPLE_SIZE = 20;

  function stripNumeric(s) {
    return String(s).replace(/[,$%\s]/g, "");
  }

  function detectType(values) {
    const sample = values.filter(v => v !== "" && v != null).slice(0, SAMPLE_SIZE);
    if (sample.length === 0) return "string";
    if (sample.every(v => !isNaN(parseFloat(stripNumeric(v))) && isFinite(stripNumeric(v)))) {
      return "number";
    }
    if (sample.every(v => !isNaN(Date.parse(v)))) {
      return "date";
    }
    return "string";
  }

  function compare(a, b, type) {
    const aEmpty = a === "" || a == null;
    const bEmpty = b === "" || b == null;
    if (aEmpty && bEmpty) return 0;
    if (aEmpty) return 1;        // empties sort last regardless of dir
    if (bEmpty) return -1;
    if (type === "number") return parseFloat(stripNumeric(a)) - parseFloat(stripNumeric(b));
    if (type === "date")   return Date.parse(a) - Date.parse(b);
    return String(a).toLowerCase().localeCompare(String(b).toLowerCase(), undefined, { numeric: true });
  }

  function getCellValue(tr, idx) {
    const td = tr.cells[idx];
    if (!td) return "";
    if (td.dataset.sortValue !== undefined) return td.dataset.sortValue;
    return (td.textContent || "").trim();
  }

  function clearIndicators(headerRow) {
    Array.from(headerRow.cells).forEach(c => {
      delete c.dataset.sortDir;
      c.classList.remove("sort-asc", "sort-desc");
    });
  }

  function applySort(table, headerRow, idx, dir) {
    const tbody = table.tBodies[0];
    if (!tbody) return;
    const rows = Array.from(tbody.rows);
    if (rows.length < 2) return;

    const values = rows.map(r => getCellValue(r, idx));
    const type = detectType(values);

    rows.sort((a, b) => {
      const cmp = compare(getCellValue(a, idx), getCellValue(b, idx), type);
      return dir === "asc" ? cmp : -cmp;
    });
    rows.forEach(r => tbody.appendChild(r));

    clearIndicators(headerRow);
    const th = headerRow.cells[idx];
    th.dataset.sortDir = dir;
    th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");
  }

  function storageKey(tableIndex) {
    return STORAGE_PREFIX + location.pathname + "::" + tableIndex;
  }

  function attachSort(table, tableIndex) {
    if (table.dataset.sortAttached === "1") return;
    if (table.dataset.noSort === "true") return;
    const thead = table.tHead;
    if (!thead || thead.rows.length === 0) return;
    const headerRow = thead.rows[thead.rows.length - 1];

    Array.from(headerRow.cells).forEach((th, idx) => {
      if (th.dataset.noSort === "true") return;
      th.classList.add("sortable-th");
      th.addEventListener("click", () => {
        const currentDir = th.dataset.sortDir;
        const newDir = currentDir === "asc" ? "desc" : "asc";
        applySort(table, headerRow, idx, newDir);
        try {
          localStorage.setItem(storageKey(tableIndex), JSON.stringify({ idx, dir: newDir }));
        } catch (_) { /* localStorage may be unavailable */ }
      });
    });
    table.dataset.sortAttached = "1";

    // Restore previous sort if any
    try {
      const saved = localStorage.getItem(storageKey(tableIndex));
      if (saved) {
        const { idx, dir } = JSON.parse(saved);
        const th = headerRow.cells[idx];
        if (th && th.dataset.noSort !== "true") {
          applySort(table, headerRow, idx, dir);
        }
      }
    } catch (_) { /* ignore parse errors */ }
  }

  function attachAllInScope(scope) {
    const root = scope || document.querySelector("main") || document.body;
    if (!root) return;
    const tables = root.querySelectorAll("table");
    tables.forEach((table, i) => attachSort(table, i));
  }

  function init() {
    attachAllInScope();
    document.body.addEventListener("htmx:afterSwap", (e) => {
      attachAllInScope(e.detail && e.detail.target ? e.detail.target : null);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
