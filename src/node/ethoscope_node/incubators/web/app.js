/* Minimal vanilla-JS UI for the standalone incubator server.
 * Talks to /api/incubators and /api/incubators/<name>/* — see routes.py.
 */
(function () {
  "use strict";

  const REFRESH_MS = 15000;
  const tbody = document.querySelector("#incubators tbody");
  const banner = document.querySelector("#discovered-banner");
  const statusLine = document.querySelector("#status-line");
  const lastRefresh = document.querySelector("#last-refresh");
  const dialog = document.querySelector("#edit-dialog");
  const form = document.querySelector("#edit-form");
  const hostnameSelect = document.querySelector("#hostname-select");

  let editing = null; // { mode: 'add' | 'edit', originalName: string | null }
  let merged = {};

  function fmt(v, dash = "—") {
    return v === undefined || v === null || v === "" ? dash : v;
  }

  function hoursFromMinutes(m) {
    if (m === undefined || m === null) return 24;
    const n = parseInt(m, 10);
    if (!Number.isFinite(n)) return 24;
    return Math.round(n / 60);
  }

  function tagDot(cls) {
    const span = document.createElement("span");
    span.className = "dot " + cls;
    return span;
  }

  function liveStatusBadge(record) {
    const td = document.createElement("td");
    if (record.source === "discovered" || record.live_status === "online") {
      td.append(tagDot("online"));
      const temp = record.temperature !== undefined && record.temperature !== null
        ? `${Number(record.temperature).toFixed(1)} °C`
        : "—";
      td.appendChild(document.createTextNode(temp));
      if (record.light_level !== undefined && record.light_level !== null) {
        const span = document.createElement("span");
        span.className = "muted";
        span.style.marginLeft = "0.5em";
        span.textContent = `· light ${record.light_level}%`;
        td.appendChild(span);
      }
    } else if (record.live_status === "offline") {
      td.append(tagDot("offline"));
      td.appendChild(document.createTextNode("offline"));
    } else {
      td.append(tagDot("unbound"));
      td.appendChild(document.createTextNode("not linked"));
    }
    return td;
  }

  function rowActions(name, isDiscovered) {
    const td = document.createElement("td");
    td.className = "row-actions";
    if (isDiscovered) {
      const linkBtn = document.createElement("button");
      linkBtn.textContent = "Link…";
      linkBtn.onclick = () => openDialogForAdd({ hostname: name, name: name });
      td.appendChild(linkBtn);
      return td;
    }
    const editBtn = document.createElement("button");
    editBtn.textContent = "Edit";
    editBtn.onclick = () => openDialogForEdit(name);
    td.appendChild(editBtn);

    const pushBtn = document.createElement("button");
    pushBtn.textContent = "Push";
    pushBtn.onclick = () => pushNow(name);
    td.appendChild(pushBtn);

    const delBtn = document.createElement("button");
    delBtn.textContent = "Delete";
    delBtn.onclick = () => confirmDelete(name);
    td.appendChild(delBtn);
    return td;
  }

  function renderRow(name, record) {
    const tr = document.createElement("tr");
    const isDiscovered = record.source === "discovered";

    const td = (text) => {
      const cell = document.createElement("td");
      cell.textContent = text;
      return cell;
    };

    tr.appendChild(td(name));
    tr.appendChild(td(fmt(record.hostname)));
    tr.appendChild(td(
      `${fmt(record.lights_on, "—")} / ${fmt(record.lights_off, "—")}`
    ));
    tr.appendChild(td(String(hoursFromMinutes(record.light_period_minutes))));
    tr.appendChild(td(
      `${fmt(record.fade_in_seconds, 1)} / ${fmt(record.fade_out_seconds, 1)}`
    ));
    tr.appendChild(td(fmt(record.max_light, 100)));
    tr.appendChild(liveStatusBadge(record));
    tr.appendChild(rowActions(name, isDiscovered));
    return tr;
  }

  async function fetchMerged() {
    try {
      const resp = await fetch("/api/incubators");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      merged = await resp.json();
      tbody.innerHTML = "";
      const names = Object.keys(merged).sort();
      for (const name of names) {
        tbody.appendChild(renderRow(name, merged[name]));
      }
      updateDiscoveredBanner();
      populateHostnameSelect();
      lastRefresh.textContent = `Last refresh: ${new Date().toLocaleTimeString()}`;
      statusLine.innerHTML = `<span class="muted">${names.length} incubator(s)</span>`;
    } catch (e) {
      statusLine.innerHTML = `<span style="color:var(--err)">Backend unreachable: ${e.message}</span>`;
    }
  }

  function updateDiscoveredBanner() {
    const discovered = Object.values(merged).filter((r) => r.source === "discovered");
    if (discovered.length === 0) {
      banner.classList.add("hidden");
      banner.textContent = "";
      return;
    }
    banner.classList.remove("hidden");
    const names = discovered.map((r) => `<code>${r.hostname}</code>`).join(", ");
    banner.innerHTML =
      `${discovered.length} unit(s) discovered on the network are not yet linked: ${names}. ` +
      `Click "Link…" on a row to attach it to a new record.`;
  }

  function populateHostnameSelect() {
    const hosts = new Set();
    for (const r of Object.values(merged)) {
      if (r.hostname) hosts.add(r.hostname);
      if (r.source === "discovered" && r.name) hosts.add(r.name);
    }
    const currentValue = hostnameSelect.value;
    hostnameSelect.innerHTML = '<option value="">— Not linked —</option>';
    Array.from(hosts).sort().forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = h;
      hostnameSelect.appendChild(opt);
    });
    if (currentValue) hostnameSelect.value = currentValue;
  }

  function openDialogForAdd(prefill = {}) {
    editing = { mode: "add", originalName: null };
    document.querySelector("#dialog-title").textContent = "Add incubator";
    form.reset();
    if (prefill.name) form.name.value = prefill.name;
    if (prefill.hostname) {
      form.hostname.value = prefill.hostname;
    }
    dialog.showModal();
  }

  function openDialogForEdit(name) {
    const record = merged[name];
    if (!record) return;
    editing = { mode: "edit", originalName: name };
    document.querySelector("#dialog-title").textContent = `Edit ${name}`;
    form.reset();
    form.name.value = name;
    form.location.value = record.location || "";
    form.owner.value = record.owner || "";
    form.description.value = record.description || "";
    form.lights_on.value = record.lights_on || "";
    form.lights_off.value = record.lights_off || "";
    form.period_hours.value = hoursFromMinutes(record.light_period_minutes);
    form.light_cycle_anchor.value =
      record.light_cycle_anchor === null || record.light_cycle_anchor === undefined
        ? ""
        : record.light_cycle_anchor;
    form.fade_in_seconds.value = record.fade_in_seconds ?? 1;
    form.fade_out_seconds.value = record.fade_out_seconds ?? 1;
    form.max_light.value = record.max_light ?? 100;
    form.hostname.value = record.hostname || "";
    dialog.showModal();
  }

  async function save() {
    const payload = {
      name: form.name.value.trim(),
      location: form.location.value,
      owner: form.owner.value,
      description: form.description.value,
      lights_on: form.lights_on.value,
      lights_off: form.lights_off.value,
      light_period_minutes:
        parseInt(form.period_hours.value, 10) * 60 || 1440,
      light_cycle_anchor:
        form.light_cycle_anchor.value === ""
          ? null
          : parseFloat(form.light_cycle_anchor.value),
      fade_in_seconds: parseInt(form.fade_in_seconds.value, 10) || 0,
      fade_out_seconds: parseInt(form.fade_out_seconds.value, 10) || 0,
      max_light: parseInt(form.max_light.value, 10) || 100,
      hostname: form.hostname.value || null,
    };

    let endpoint = "/api/incubators";
    let method = "POST";
    if (editing.mode === "edit") {
      endpoint = `/api/incubators/${encodeURIComponent(editing.originalName)}`;
      method = "PUT";
    }
    try {
      const resp = await fetch(endpoint, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await resp.json();
      if (result.result !== "success") {
        alert(result.message || "Error saving incubator.");
        return;
      }
      // If we just added (or saved) a record with a hostname binding, the
      // backend already pushed; we just need to refresh the table.
      dialog.close();
      await fetchMerged();
    } catch (e) {
      alert(`Network error: ${e.message}`);
    }
  }

  async function pushNow(name) {
    try {
      const resp = await fetch(
        `/api/incubators/${encodeURIComponent(name)}/push`,
        { method: "POST" }
      );
      const result = await resp.json();
      if (result.result === "success") {
        statusLine.innerHTML = `<span style="color:var(--ok)">Pushed ${name}</span>`;
      } else {
        alert(result.message || "Push failed.");
      }
    } catch (e) {
      alert(`Network error: ${e.message}`);
    }
  }

  async function confirmDelete(name) {
    if (!confirm(`Delete incubator '${name}'? This is permanent.`)) return;
    try {
      const resp = await fetch(
        `/api/incubators/${encodeURIComponent(name)}`,
        { method: "DELETE" }
      );
      const result = await resp.json();
      if (result.result !== "success") {
        alert(result.message || "Delete failed.");
        return;
      }
      await fetchMerged();
    } catch (e) {
      alert(`Network error: ${e.message}`);
    }
  }

  document.querySelector("#add-btn").onclick = () => openDialogForAdd();
  document.querySelector("#refresh-btn").onclick = fetchMerged;
  document.querySelector("#save-btn").onclick = save;
  document.querySelector("#cancel-btn").onclick = () => dialog.close();

  fetchMerged();
  setInterval(fetchMerged, REFRESH_MS);
})();
