import { app } from "../../scripts/app.js";

/**
 * Donut merged-node widget visibility.
 *
 * Several Donut nodes were consolidated into multipurpose nodes with a mode
 * selector. ComfyUI has no native conditional widgets, so the Python side
 * declares the union of every mode's widgets as optional and ignores the
 * irrelevant ones at runtime. This extension hides the widgets that don't
 * belong to the currently selected mode so each mode shows a clean UI.
 *
 * Purely cosmetic: if this script fails to load the nodes still work, they
 * just show all widgets at once. Hidden widgets keep their values and still
 * serialize, so toggling modes is lossless.
 */

// node id (NODE_CLASS_MAPPINGS key) -> { selector widget, value -> active widget names }
const CONFIG = {

  "DonutLoRACivitAILookup": {
    selector: "source",
    modes: {
      "LoRA File": ["lora_name", "api_key", "force_refresh"],
      "Hash": ["hash", "api_key"],
    },
  },

};

const HIDDEN = "donuthidden-";

function hideWidget(w) {
  if (!w || (typeof w.type === "string" && w.type.startsWith(HIDDEN))) return;
  w._donutType = w.type;
  w._donutCompute = w.computeSize;
  w.type = HIDDEN + w.type;
  w.computeSize = () => [0, -4];
  w.hidden = true;            // modern ComfyUI frontend honors this; legacy ignores it
}

function showWidget(w) {
  if (!w || typeof w.type !== "string" || !w.type.startsWith(HIDDEN)) return;
  w.type = w._donutType;
  w.computeSize = w._donutCompute;
  w.hidden = false;
  delete w._donutType;
  delete w._donutCompute;
}

function applyVisibility(node, cfg) {
  if (!node.widgets) return;
  const sel = node.widgets.find((w) => w.name === cfg.selector);
  if (!sel) return;
  const active = new Set(cfg.modes[sel.value] || []);
  for (const name of cfg.managed) {
    if (name === cfg.selector) continue;
    const w = node.widgets.find((x) => x.name === name);
    if (!w) continue; // name may be an input slot, not a widget — skip
    if (active.has(name)) showWidget(w);
    else hideWidget(w);
  }
  const sz = node.computeSize();
  node.setSize([Math.max(node.size[0], sz[0]), sz[1]]);
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "donut.mergedNodes.widgetVisibility",
  beforeRegisterNodeDef(nodeType, nodeData) {
    const cfg = CONFIG[nodeData?.name];
    if (!cfg) return;
    // union of every mode's widgets = the set this node manages
    cfg.managed = [...new Set(Object.values(cfg.modes).flat())];

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      const self = this;
      const sel = this.widgets?.find((w) => w.name === cfg.selector);
      if (sel) {
        const prev = sel.callback;
        sel.callback = function () {
          const rr = prev?.apply(this, arguments);
          applyVisibility(self, cfg);
          return rr;
        };
      }
      applyVisibility(this, cfg);
      return r;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      applyVisibility(this, cfg);
      return r;
    };
  },
});
