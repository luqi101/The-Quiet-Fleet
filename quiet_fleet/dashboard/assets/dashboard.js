const byId = (id) => document.getElementById(id);
const atInput = byId("as-of");
const serialInput = byId("serial");
const ownerFilter = byId("owner-filter");
const priorityFilter = byId("priority-filter");
const queueItems = byId("queue-items");
const lookupResult = byId("lookup-result");
const drawer = byId("evidence-drawer");

const localTime = (timeZone) => new Intl.DateTimeFormat("en-CA", {
  timeZone,
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZoneName: "longOffset",
});
const depotTimes = [
  [byId("time-mss"), localTime("America/Toronto")],
  [byId("time-reg"), localTime("America/Regina")],
];

let snapshot;
let queueRequest;
let deviceRequest;
let evidenceOpener;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function label(value) {
  if (value === "none") return "None";
  return value[0].toUpperCase() + value.slice(1).replaceAll("_", " ");
}

function message(id, text) {
  const node = byId(id);
  node.textContent = text;
  node.hidden = !text;
}

function list(values) {
  const node = element("ul", undefined, "reasons");
  node.replaceChildren(...values.map((value) => element("li", value)));
  return node;
}

async function getJSON(path, at, signal) {
  const query = new URLSearchParams({at});
  let response;
  try {
    response = await fetch(`${path}?${query}`, {signal, headers: {Accept: "application/json"}});
  } catch (error) {
    if (signal.aborted) throw error;
    throw new Error("Could not reach the local service. Check that it is running and try again.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : "Request failed.";
    throw new Error(`${detail} (HTTP ${response.status})`);
  }
  if (!data || typeof data.at !== "string") {
    throw new Error("The service returned an unexpected response. Try loading the checkpoint again.");
  }
  return data;
}

function setCheckpoint(at) {
  const date = at ? new Date(at) : null;
  for (const [node, formatter] of depotTimes) {
    if (!date) {
      node.textContent = "—";
      continue;
    }
    node.replaceChildren(...formatter.formatToParts(date).map((part) => (
      part.type === "timeZoneName" ? element("span", part.value, "depot-offset") : document.createTextNode(part.value)
    )));
  }
  for (const control of [serialInput, byId("lookup-button"), ownerFilter, priorityFilter]) {
    control.disabled = !at;
  }
  byId("lookup-time").textContent = at ? `As of ${at}` : "Load a checkpoint to look up a device.";
}

function evidenceButton(ids, context, at) {
  const button = element("button", `Evidence (${ids.length})`);
  button.type = "button";
  button.setAttribute("aria-haspopup", "dialog");
  button.addEventListener("click", () => {
    evidenceOpener = button;
    byId("evidence-context").textContent = `${context}\nAs of ${at}`;
    byId("evidence-empty").hidden = ids.length > 0;
    byId("evidence-ids").replaceChildren(...ids.map((id) => {
      const entry = element("li");
      entry.append(element("code", id));
      return entry;
    }));
    drawer.showModal();
  });
  return button;
}

function field(name, value, className) {
  const entry = element("div", undefined, className);
  entry.append(element("dt", name), element("dd", value));
  return entry;
}

function deviceSummary(item) {
  const assets = item.asset_ids.join(", ") || "No assigned asset";
  return `${item.serials.join(", ")} · ${assets}`;
}

function incidentDetails(item) {
  const details = element("details");
  details.append(element("summary", "Affected devices and assets"));
  const members = element("dl", undefined, "members");
  members.append(
    element("dt", "Devices"), element("dd", item.serials.join(", ")),
    element("dt", "Assets"), element("dd", item.asset_ids.join(", ") || "No assigned assets"),
  );
  details.append(members);
  return details;
}

function queueCard(item, at) {
  const incident = item.kind === "incident";
  const cause = item.likely_cause === "unknown" ? "Cause unconfirmed" : label(item.likely_cause);
  const scope = incident ? `${item.serials.length} devices · ${item.asset_ids.length} assets` : deviceSummary(item);
  const owner = item.who_acts === "none" ? "Unassigned" : label(item.who_acts);
  const row = element("li", undefined, "card panel");
  row.dataset.itemId = item.item_id;

  const header = element("div", undefined, "card-header");
  const heading = element("div");
  heading.append(element("h3", cause), element("p", incident ? `Incident · ${scope}` : scope, "card-meta"));
  const priority = element("span", `${label(item.priority)} priority`, "priority");
  priority.dataset.level = item.priority;
  header.append(heading, priority);

  const action = element("div", undefined, "action");
  action.append(element("strong", `Next action · ${owner}`), element("p", item.next_action));
  const footer = element("div", undefined, "card-footer");
  if (incident) footer.append(incidentDetails(item));
  footer.append(evidenceButton(item.evidence, `${cause} · ${scope}`, at));
  row.append(header, action, list(item.reasons), footer);
  return row;
}

function renderQueue() {
  if (!snapshot) return;
  const matches = snapshot.items.filter((item) => (
    (!ownerFilter.value || item.who_acts === ownerFilter.value) &&
    (!priorityFilter.value || item.priority === priorityFilter.value)
  ));
  const total = snapshot.items.length;
  const count = matches.length === total ? String(total) : `${matches.length} of ${total}`;
  message("queue-summary", `${count} ${total === 1 ? "item" : "items"}`);
  byId("queue-empty").hidden = matches.length > 0;
  byId("empty-title").textContent = total ? "No items match these filters" : "No actions at this checkpoint";
  byId("empty-help").textContent = total
    ? "Change the owner or priority filter to see more actions."
    : "No events ingested yet? Send events to POST /ingest, then load the queue again.";
  queueItems.replaceChildren(...matches.map((item) => queueCard(item, snapshot.at)));
}

async function loadQueue() {
  queueRequest?.abort();
  deviceRequest?.abort();
  const controller = queueRequest = new AbortController();
  const requestedAt = atInput.value.trim();
  const inputValue = atInput.value;
  snapshot = undefined;
  if (drawer.open) drawer.close();
  setCheckpoint(null);
  message("lookup-message", "");
  message("lookup-error", "");
  lookupResult.replaceChildren();
  lookupResult.setAttribute("aria-busy", "false");
  queueItems.replaceChildren();
  queueItems.setAttribute("aria-busy", "true");
  byId("queue-empty").hidden = true;
  message("queue-error", "");
  message("queue-summary", "Loading support queue…");

  try {
    const data = await getJSON("/triage", requestedAt, controller.signal);
    if (controller.signal.aborted) return;
    if (!Array.isArray(data.items)) throw new Error("The service returned an unexpected queue response.");
    snapshot = data;
    setCheckpoint(data.at);
    if (atInput.value === inputValue) atInput.value = data.at;
    renderQueue();
  } catch (error) {
    if (controller.signal.aborted) return;
    message("queue-summary", "");
    message("queue-error", error.message);
  } finally {
    if (queueRequest === controller) queueItems.setAttribute("aria-busy", "false");
  }
}

function renderDevice(device) {
  const result = element("div", undefined, "device-result");
  const fields = element("dl", undefined, "device-fields");
  fields.append(
    field("State", label(device.state)),
    field("Likely cause", label(device.likely_cause)),
    field("Asset", device.asset_id ?? "Unassigned"),
    field("Evidence confidence", device.confidence.toFixed(2)),
    field("Last heard (UTC)", device.last_heard_at ?? "No contact by this time", "full"),
  );
  result.append(
    element("h3", device.serial), fields, list(device.reasons),
    evidenceButton(device.evidence, `${device.serial} · ${label(device.likely_cause)}`, device.at),
  );
  lookupResult.replaceChildren(result);
}

async function lookupDevice() {
  if (!snapshot || !serialInput.value.trim()) return;
  deviceRequest?.abort();
  const controller = deviceRequest = new AbortController();
  const serial = encodeURIComponent(serialInput.value.trim());
  lookupResult.replaceChildren();
  lookupResult.setAttribute("aria-busy", "true");
  message("lookup-error", "");
  message("lookup-message", "Looking up device…");

  try {
    const device = await getJSON(`/devices/${serial}/status`, snapshot.at, controller.signal);
    if (controller.signal.aborted) return;
    renderDevice(device);
  } catch (error) {
    if (controller.signal.aborted) return;
    message("lookup-error", error.message);
  } finally {
    if (deviceRequest === controller && !controller.signal.aborted) {
      lookupResult.setAttribute("aria-busy", "false");
      message("lookup-message", "");
    }
  }
}

byId("checkpoint-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadQueue();
});
byId("lookup-form").addEventListener("submit", (event) => {
  event.preventDefault();
  lookupDevice();
});
for (const filter of [ownerFilter, priorityFilter]) filter.addEventListener("change", renderQueue);
byId("close-evidence").addEventListener("click", () => drawer.close());
drawer.addEventListener("close", () => {
  if (evidenceOpener?.isConnected) evidenceOpener.focus();
});

loadQueue();
