"use strict";

const assert = require("node:assert/strict");
const { buildResultItems, buildSummary, explainCandidate } = require("./moment-rules.js");

const payload = {
  candidate_document: {
    candidates: [
      { id: "cand_0001", bbox: { x: 10, y: 20, width: 80, height: 40 }, score: 0.88, source: "opencv_contour", reasons: ["interaction:control_geometry"] },
      { id: "cand_0002", bbox: { x: 20, y: 80, width: 90, height: 42 }, score: 0.62, source: "opencv_contour", reasons: ["branch:canny"] },
    ],
  },
  report: {
    diagnostics: {
      visual_candidate_count: 3,
      active_region: null,
      suppressed_candidates: [
        { id: "cand_0003", bbox: { x: 1, y: 1, width: 5, height: 5 }, score: 0.2, source: "opencv_contour", reasons: ["semantic:tiny_fragment"], stage: "semantic_filter", decision_reason: "below_score_threshold" },
      ],
    },
  },
};

const items = buildResultItems(payload);
assert.deepEqual(items.map((item) => item.decision), ["keep", "pending", "ignored"]);
assert.equal(explainCandidate(items[0]).badge, "建议保留");
assert.equal(explainCandidate(items[1]).badge, "需要确认");
assert.equal(explainCandidate(items[2]).badge, "规则忽略");
assert.deepEqual(buildSummary(payload, items), {
  keep: 1,
  pending: 1,
  ignored: 1,
  initial: 3,
  final: 2,
  activeRegion: null,
  text: "从 3 个初始候选中形成 2 个最终建议，其中 1 个需要人工确认。",
  pageState: "当前页面未检测到需要隔离背景控件的活动层。",
});

console.log("moment rules: decisions, explanations and summary passed");
