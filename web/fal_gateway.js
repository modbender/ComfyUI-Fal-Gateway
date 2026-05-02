// ComfyUI-Fal-Gateway frontend extension.
//
// Three responsibilities:
//   1. Per-model dynamic widget rendering (M4) — fetch each model's WidgetSpec
//      list from /fal_gateway/schema/<id_b64> and rebuild the node's widgets
//      whenever the user picks a different model. Static widgets (model_id,
//      prompt, image_count) and image SOCKETS are left alone.
//   2. Reference-style nodes (Ref2V, Ref2I): reflect the `image_count` widget
//      value by adding/removing image_N sockets (1..4) — switch pattern.
//   3. "Fal-Gateway: refresh catalog cache" right-click menu option on every
//      Fal-Gateway node.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Reference-style nodes that have a dynamic image_count switch.
const REF_NODES = new Set(["FalGatewayRef2V", "FalGatewayRef2I"]);
const IMAGE_PREFIX = "image_";
const MAX_IMAGES = 4;

function findInputIndex(node, name) {
  return (node.inputs || []).findIndex((s) => s && s.name === name);
}

function syncImageSockets(node, count) {
  count = Math.max(1, Math.min(MAX_IMAGES, Math.floor(count || 1)));
  // Remove image_N where N > count (high → low to keep indices stable).
  for (let n = MAX_IMAGES; n > count; n--) {
    const idx = findInputIndex(node, `${IMAGE_PREFIX}${n}`);
    if (idx >= 0) node.removeInput(idx);
  }
  // Add image_N for 1..count if missing.
  for (let n = 1; n <= count; n++) {
    if (findInputIndex(node, `${IMAGE_PREFIX}${n}`) < 0) {
      node.addInput(`${IMAGE_PREFIX}${n}`, "IMAGE");
    }
  }
  // Grow only — never shrink below the user's manual resize. computeSize()
  // returns the MINIMUM required for current sockets/widgets; if the user has
  // resized larger we keep their size, otherwise bump to the new minimum.
  const min = node.computeSize();
  const cur = node.size || min;
  node.setSize([Math.max(cur[0], min[0]), Math.max(cur[1], min[1])]);
  node.setDirtyCanvas(true, true);
}

function getCountWidget(node) {
  return node.widgets?.find((w) => w && w.name === "image_count");
}

function ensureCountCallback(node) {
  const w = getCountWidget(node);
  if (!w || w.__falGatewayPatched) return w;
  const orig = w.callback;
  w.callback = function (value, ...rest) {
    const r = orig?.call(this, value, ...rest);
    syncImageSockets(node, value);
    return r;
  };
  w.__falGatewayPatched = true;
  return w;
}

app.registerExtension({
  name: "ComfyUI.FalGateway.DynamicRefSockets",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!REF_NODES.has(nodeData?.name)) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      const w = ensureCountCallback(this);
      // Fresh node: trim sockets to default count.
      if (w) syncImageSockets(this, w.value);
      return r;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (...args) {
      const r = onConfigure?.apply(this, args);
      // Restored workflow: widget values are loaded; resync sockets to match.
      const w = ensureCountCallback(this);
      if (w) syncImageSockets(this, w.value);
      return r;
    };
  },
});

// Refresh-cache + dynamic-widget extensions cover every Fal-Gateway node.
// Adding a new node = one entry here.
const FAL_NODE_TYPES = new Set([
  "FalGatewayT2V",
  "FalGatewayI2V",
  "FalGatewayRef2V",
  "FalGatewayT2I",
  "FalGatewayI2I",
  "FalGatewayRef2I",
  "FalGatewayUpscale",
  "FalGatewayT2T",
  "FalGatewayI2T",
]);
const REFRESH_ROUTE = "/fal_gateway/refresh";

async function refreshFalCatalog() {
  let res;
  try {
    res = await api.fetchApi(REFRESH_ROUTE, { method: "POST" });
  } catch (err) {
    alert("Fal-Gateway: refresh request failed — " + err.message);
    return;
  }
  let data = {};
  try {
    data = await res.json();
  } catch (_e) {
    /* non-JSON body */
  }
  if (!res.ok || data.ok === false) {
    alert("Fal-Gateway: refresh failed — " + (data.error || res.statusText));
    return;
  }
  alert(
    data.message ||
      "Fal-Gateway: cache cleared. Restart ComfyUI to pick up the fresh model dropdowns.",
  );
}

app.registerExtension({
  name: "ComfyUI.FalGateway.RefreshMenu",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!FAL_NODE_TYPES.has(nodeData?.name)) return;
    const orig = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (_, options) {
      orig?.apply(this, arguments);
      options.unshift({
        content: "Fal-Gateway: refresh catalog cache",
        callback: () => {
          refreshFalCatalog();
        },
      });
    };
  },
});

// ============================================================================
// M4: per-model dynamic widget rendering
// ============================================================================
// When the user changes the model_id dropdown, fetch that model's WidgetSpec
// list from /fal_gateway/schema/<id_b64> and rebuild the node's non-static
// widgets in place. Static widgets (model_id, prompt, image_count) stay; image
// SOCKETS are not touched here (they live in node.inputs).

const SCHEMA_ROUTE = "/fal_gateway/schema";
const SCHEMA_CACHE = new Map();
const STATIC_WIDGET_NAMES = new Set(["model_id", "prompt", "image_count"]);

// ============================================================================
// Cost estimator (v0.4.0)
// ============================================================================
// The schema endpoint returns {unit_price, unit, currency} per model. We render
// a non-serialized "estimated_cost" label widget on every Fal-Gateway node that
// updates whenever the user changes the model OR any dynamic widget value.
//
// Tokens-priced models honestly show the per-token rate (no fake total — input
// /output token counts aren't predictable pre-call).

const COST_LABEL_WIDGET_NAME = "estimated_cost";
const COST_LABEL_LOADING = "Estimated cost: …";
const COST_LABEL_UNAVAILABLE = "Estimated cost: pricing unavailable";

// Currency symbol map. Adding a currency = one entry. Falls back to bare code.
const CURRENCY_SYMBOLS = { USD: "$", EUR: "€", GBP: "£" };

function fmtMoney(amount, currency) {
  const sym = CURRENCY_SYMBOLS[currency] ?? `${currency || "USD"} `;
  // Choose precision based on magnitude — pricing < $0.01 needs 4 dp.
  const precision = amount < 0.01 ? 4 : amount < 1 ? 3 : 2;
  return `${sym}${amount.toFixed(precision)}`;
}

// Normalise fal's unit string into the lookup key for COST_FORMULAS.
// Handles plural, spacing, and case variation. Adding a new alias = one entry.
const UNIT_ALIASES = {
  seconds: "second",
  minutes: "minute",
  images: "image",
  megapixels: "megapixel",
  tokens: "token",
  m_tokens: "1m_tokens",
  tokens_1m: "1m_tokens",
  per_1m_tokens: "1m_tokens",
  "1_million_tokens": "1m_tokens",
};

function normalizeUnit(unit) {
  if (!unit) return "";
  const u = String(unit).toLowerCase().trim().replace(/\s+/g, "_");
  return UNIT_ALIASES[u] ?? u;
}

function pickWidgetValue(widgets, names) {
  for (const n of names) {
    const w = widgets.find((x) => x?.name === n);
    if (w && typeof w.value === "number") return w.value;
    if (w && typeof w.value === "string" && !Number.isNaN(parseFloat(w.value)))
      return parseFloat(w.value);
  }
  return null;
}

// Registry: one entry per fal `unit` value. Adding a new unit = one entry.
// Each formula receives {price, currency, widgets} (widgets keyed by name)
// and returns the label string to display.
const COST_FORMULAS = {
  image: ({ price, currency }) =>
    `Estimated cost: ${fmtMoney(price, currency)} per image`,

  second: ({ price, currency, widgets }) => {
    const dur = pickWidgetValue(widgets, ["duration", "duration_seconds", "seconds"]);
    if (dur != null && dur > 0) {
      const total = price * dur;
      return `Estimated cost: ${fmtMoney(total, currency)} (${dur}s × ${fmtMoney(price, currency)}/s)`;
    }
    return `Estimated cost: ${fmtMoney(price, currency)} per second`;
  },

  minute: ({ price, currency, widgets }) => {
    const dur = pickWidgetValue(widgets, ["duration", "duration_seconds", "seconds"]);
    if (dur != null && dur > 0) {
      const total = (price * dur) / 60;
      return `Estimated cost: ${fmtMoney(total, currency)} (${dur}s ÷ 60 × ${fmtMoney(price, currency)}/min)`;
    }
    return `Estimated cost: ${fmtMoney(price, currency)} per minute`;
  },

  megapixel: ({ price, currency, widgets }) => {
    // Try image_size {width,height}, fall back to known w/h widgets.
    const w = pickWidgetValue(widgets, ["width"]);
    const h = pickWidgetValue(widgets, ["height"]);
    if (w && h) {
      const mp = (w * h) / 1_000_000;
      const total = price * mp;
      return `Estimated cost: ${fmtMoney(total, currency)} (${mp.toFixed(2)} MP × ${fmtMoney(price, currency)}/MP)`;
    }
    return `Estimated cost: ${fmtMoney(price, currency)} per megapixel`;
  },

  "1m_tokens": ({ price, currency }) =>
    `Estimated cost: ${fmtMoney(price, currency)} per 1M tokens (varies by usage)`,

  token: ({ price, currency }) =>
    `Estimated cost: ${fmtMoney(price * 1_000_000, currency)} per 1M tokens (varies by usage)`,

  // Fallback for unknown / future unit types — show raw rate.
  __default: ({ price, currency, unit }) =>
    `Estimated cost: ${fmtMoney(price, currency)} per ${unit || "unit"}`,
};

function ensureCostLabel(node) {
  let label = node.widgets?.find((w) => w?._falCostLabel);
  if (label) return label;
  // serialize:false keeps it out of saved workflow JSON (it's UI-only).
  label = node.addWidget("text", COST_LABEL_WIDGET_NAME, COST_LABEL_LOADING, null, {
    serialize: false,
  });
  label._falCostLabel = true;
  // Make it read-only-feeling: clobber any user edits back to the computed value.
  const origCallback = label.callback;
  label.callback = function (value, ...rest) {
    origCallback?.call(this, value, ...rest);
    recomputeCost(node);
  };
  return label;
}

function recomputeCost(node) {
  const label = node.widgets?.find((w) => w?._falCostLabel);
  if (!label) return;
  const pricing = node._falPricing;
  if (!pricing || pricing.unit_price == null) {
    label.value = COST_LABEL_UNAVAILABLE;
    node.setDirtyCanvas(true, false);
    return;
  }
  const unitKey = normalizeUnit(pricing.unit);
  const formula = COST_FORMULAS[unitKey] ?? COST_FORMULAS.__default;
  label.value = formula({
    price: pricing.unit_price,
    currency: pricing.currency || "USD",
    unit: pricing.unit,
    widgets: node.widgets || [],
  });
  node.setDirtyCanvas(true, false);
}

function modelIdToBase64Url(modelId) {
  // Standard URL-safe base64 (RFC 4648 §5), no padding.
  return btoa(modelId)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function fetchModelSchema(modelId) {
  if (SCHEMA_CACHE.has(modelId)) return SCHEMA_CACHE.get(modelId);
  const url = `${SCHEMA_ROUTE}/${modelIdToBase64Url(modelId)}`;
  const res = await api.fetchApi(url);
  if (!res.ok) {
    throw new Error(`schema fetch failed: HTTP ${res.status}`);
  }
  const data = await res.json();
  if (data.ok === false) {
    throw new Error(data.error || "schema fetch returned ok=false");
  }
  SCHEMA_CACHE.set(modelId, data);
  return data;
}

function makeDynamicWidget(node, spec) {
  const name = spec.name;
  const def = spec.default;
  const meta = spec.meta || {};

  if (spec.kind === "STRING") {
    return node.addWidget("text", name, def ?? "", null, {
      multiline: !!spec.multiline,
    });
  }
  if (spec.kind === "INT") {
    return node.addWidget("number", name, Number(def) || 0, null, {
      min: meta.min,
      max: meta.max,
      step: 1,
      precision: 0,
    });
  }
  if (spec.kind === "FLOAT") {
    return node.addWidget("number", name, Number(def) || 0, null, {
      min: meta.min,
      max: meta.max,
      step: meta.step ?? 0.01,
      precision: 3,
    });
  }
  if (spec.kind === "BOOLEAN") {
    return node.addWidget("toggle", name, !!def, null);
  }
  if (spec.kind === "COMBO") {
    const options = Array.isArray(spec.options) ? spec.options : [];
    return node.addWidget("combo", name, def ?? options[0] ?? "", null, {
      values: options,
    });
  }
  // IMAGE_INPUT / IMAGE_ARRAY → not user-editable widgets here (they're sockets).
  // JSON → fall back to multiline string.
  if (spec.kind === "JSON") {
    return node.addWidget("text", name, def ?? "", null, { multiline: true });
  }
  return null;
}

async function rebuildDynamicWidgets(node, modelId) {
  // ALWAYS clear stale dynamic widgets first so a fetch failure doesn't leave
  // the user looking at the previous model's widgets on this node.
  const previousValues = new Map();
  if (node.widgets) {
    for (const w of node.widgets) {
      if (w && w._falDynamic && w.name) {
        previousValues.set(w.name, w.value);
      }
    }
    node.widgets = node.widgets.filter((w) => !w?._falDynamic);
  }

  let schema;
  try {
    schema = await fetchModelSchema(modelId);
  } catch (err) {
    console.warn(`[FalGateway] schema fetch failed for ${modelId}:`, err);
    // Stale widgets already removed above; just resize and bail.
    node._falPricing = null;
    recomputeCost(node);
    const min = node.computeSize();
    const cur = node.size || min;
    node.setSize([Math.max(cur[0], min[0]), Math.max(cur[1], min[1])]);
    node.setDirtyCanvas(true, true);
    return;
  }

  // Stash pricing on the node for recomputeCost; updates label after rebuild.
  node._falPricing = {
    unit_price: schema.unit_price ?? null,
    unit: schema.unit ?? null,
    currency: schema.currency ?? null,
  };

  // Materialise new widgets from schema.
  for (const spec of schema.widgets || []) {
    if (!spec || !spec.name) continue;
    if (STATIC_WIDGET_NAMES.has(spec.name)) continue;
    if (spec.kind === "IMAGE_INPUT" || spec.kind === "IMAGE_ARRAY") continue;
    const w = makeDynamicWidget(node, spec);
    if (!w) continue;
    w._falDynamic = true;
    // Carry over the previously-set value if the new model also has a widget
    // by the same name (e.g. duration, seed, prompt-style fields). Reduces
    // re-typing when the user A/B-tests two similar models.
    if (previousValues.has(spec.name)) {
      w.value = previousValues.get(spec.name);
    }
    // Trigger cost recomputation whenever the user changes this widget — a
    // duration / width / height change should bump the displayed total.
    const origCallback = w.callback;
    w.callback = function (value, ...rest) {
      const r = origCallback?.call(this, value, ...rest);
      recomputeCost(node);
      return r;
    };
  }
  recomputeCost(node);

  // Resize to fit; never shrink past user-set size (fixes Issue 1 for this code path too).
  const min = node.computeSize();
  const cur = node.size || min;
  node.setSize([Math.max(cur[0], min[0]), Math.max(cur[1], min[1])]);
  node.setDirtyCanvas(true, true);
}

function attachToModelIdWidget(node) {
  const widget = node.widgets?.find((w) => w?.name === "model_id");
  if (!widget || widget._falCallbackPatched) return widget;
  const origCallback = widget.callback;
  widget.callback = function (value, ...rest) {
    const r = origCallback?.call(this, value, ...rest);
    if (value && value !== "<no models available>") {
      // Fire-and-forget; rebuild handles errors internally.
      rebuildDynamicWidgets(node, value);
    }
    return r;
  };
  widget._falCallbackPatched = true;
  return widget;
}

app.registerExtension({
  name: "ComfyUI.FalGateway.DynamicSchemaWidgets",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!FAL_NODE_TYPES.has(nodeData?.name)) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      ensureCostLabel(this);
      const w = attachToModelIdWidget(this);
      if (w?.value && w.value !== "<no models available>") {
        rebuildDynamicWidgets(this, w.value);
      }
      return r;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info, ...rest) {
      // Capture the FULL saved widgets_values BEFORE the standard configure
      // applies them (only the first N apply to existing static widgets; the
      // rest are dropped before our dynamic widgets exist).
      const savedValues = (info?.widgets_values || this.widgets_values || []).slice();
      const r = onConfigure?.apply(this, [info, ...rest]);
      ensureCostLabel(this);
      const w = attachToModelIdWidget(this);
      if (w?.value && w.value !== "<no models available>") {
        rebuildDynamicWidgets(this, w.value).then(() => {
          // After rebuild: apply leftover saved values to the freshly-added
          // dynamic widgets, in order. Best-effort — if the model's schema has
          // shifted between save and load, mismatched values survive on
          // matching indices, others are dropped.
          //
          // Cost label is `serialize:false` so it's NOT in savedValues; we must
          // exclude it from the static count or every dynamic widget gets the
          // wrong saved value.
          const widgets = this.widgets || [];
          const dynamicWidgets = widgets.filter((ww) => ww?._falDynamic);
          const costLabelCount = widgets.filter((ww) => ww?._falCostLabel).length;
          const staticCount = widgets.length - dynamicWidgets.length - costLabelCount;
          for (let i = 0; i < dynamicWidgets.length; i++) {
            const idx = staticCount + i;
            if (idx < savedValues.length && savedValues[idx] !== undefined) {
              dynamicWidgets[i].value = savedValues[idx];
            }
          }
          recomputeCost(this);
          this.setDirtyCanvas(true, true);
        });
      }
      return r;
    };
  },
});
