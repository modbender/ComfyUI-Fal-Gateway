// ComfyUI-Fal-Gateway frontend extension.
//
// Initial responsibility (M3-partial / M4-prelude):
//   * On the FalGatewayRef2V node, reflect the `image_count` widget value by
//     adding/removing image_N sockets (1..4) in node.inputs. This implements the
//     "switch-like" pattern requested: only the sockets you'll use are visible.
//
// Larger M4 work (per-model dynamic widgets driven by OpenAPI schemas) lands here
// later; for now this file is intentionally narrow.

import { app } from "../../scripts/app.js";

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
  node.setSize(node.computeSize());
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

// Refresh-cache right-click option on all seven Fal-Gateway nodes.
const FAL_NODE_TYPES = new Set([
  "FalGatewayT2V",
  "FalGatewayI2V",
  "FalGatewayRef2V",
  "FalGatewayT2I",
  "FalGatewayI2I",
  "FalGatewayRef2I",
  "FalUpscale",
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
