(() => {
  "use strict";

  const REASON_LABELS = Object.freeze({
    "penalty:border_touch": "区域贴近图片边界，已降低置信度",
    "context:active_layer": "位于当前活动层内",
    "interaction:control_surface": "外观接近可交互控件表面",
    "interaction:content_support": "内部文字或图标提供了控件证据",
    "interaction:multi_branch_control": "多个视觉分支共同支持这是控件",
    "interaction:close_template": "形状与关闭控件模板一致",
    "interaction:control_geometry": "尺寸与比例符合常见控件",
    "interaction:bottom_navigation_prior": "位于常见底部导航位置",
    "interaction:wide_action_prior": "形状接近宽幅主操作按钮",
    "interaction:active_action_row": "位于活动层操作区域",
    "semantic:tiny_fragment": "区域过小，更可能是视觉碎片",
    "semantic:text_line_like": "形状更接近文本行而不是独立控件",
    "semantic:sibling_container": "更可能是包含多个控件的容器",
  });

  const DECISION_LABELS = Object.freeze({
    outside_active_layer: "位于当前活动层之外",
    active_layer_container: "它是活动层容器，不是独立点击目标",
    replaced_by_close_control: "已被更可靠的关闭控件候选替代",
    below_score_threshold: "规则评分低于候选保留阈值",
    interaction_duplicate: "与更高置信候选明显重叠",
    candidate_limit: "超过当前页面候选数量上限",
  });

  function reasonLabel(reason) {
    if (REASON_LABELS[reason]) {
      return REASON_LABELS[reason];
    }
    if (reason.startsWith("branch:close_template")) {
      return "由关闭控件模板分支发现";
    }
    if (reason.startsWith("branch:surface_close")) {
      return "检测到闭合控件表面";
    }
    if (reason.startsWith("branch:")) {
      return "由图像轮廓分支发现";
    }
    if (reason.startsWith("merge:nested_fragments=")) {
      return "合并了同一控件内的文字或图标碎片";
    }
    if (reason.startsWith("shape:rectangularity=")) {
      return "具有可复核的矩形结构";
    }
    if (reason.startsWith("shape:solidity=")) {
      return "区域轮廓较完整";
    }
    if (reason.startsWith("support:edge=")) {
      return "边缘像素提供了轮廓证据";
    }
    if (reason.startsWith("semantic:container_children=")) {
      return "内部包含多个子区域，更接近容器";
    }
    if (reason.startsWith("match:close_x=")) {
      return "关闭图标模板匹配通过";
    }
    return reason;
  }

  function uniqueSuppressed(items) {
    const seen = new Set();
    return items.filter((item) => {
      const box = item.bbox || {};
      const key = `${box.x}:${box.y}:${box.width}:${box.height}:${item.stage}:${item.decision_reason}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  }

  function buildResultItems(payload) {
    const finalCandidates = payload?.candidate_document?.candidates || [];
    const suppressed = uniqueSuppressed(payload?.report?.diagnostics?.suppressed_candidates || []);
    const finalItems = finalCandidates.map((candidate) => ({
      ...candidate,
      moment_id: `final:${candidate.id}`,
      decision: Number(candidate.score || 0) >= 0.75 ? "keep" : "pending",
      stage: "final",
    }));
    const ignoredItems = suppressed.map((candidate, index) => ({
      ...candidate,
      moment_id: `ignored:${index + 1}`,
      decision: "ignored",
    }));
    return [...finalItems, ...ignoredItems];
  }

  function candidateType(candidate) {
    const reasons = candidate.reasons || [];
    if (candidate.source === "opencv_template_match" || reasons.some((item) => item.includes("close_template"))) {
      return "可能的关闭控件";
    }
    if (reasons.includes("interaction:bottom_navigation_prior")) {
      return "可能的底部导航项";
    }
    if (reasons.includes("interaction:wide_action_prior")) {
      return "可能的主操作按钮";
    }
    if (reasons.some((item) => item.startsWith("branch:surface_close"))) {
      return "可能的独立控件表面";
    }
    return "可能的点击控件";
  }

  function explainCandidate(candidate) {
    const reasons = (candidate.reasons || []).map(reasonLabel);
    const score = Math.max(0, Math.min(1, Number(candidate.score || 0)));
    if (candidate.decision === "ignored") {
      return {
        type: candidateType(candidate),
        badge: "规则忽略",
        decision: DECISION_LABELS[candidate.decision_reason] || "未进入最终候选结果",
        why: reasons.slice(-2).join("；") || "现有过滤规则认为它不是独立点击目标。",
        suggestion: "默认不纳入当前候选；如与实际交互不符，可在专业工作台手动补充。",
        confidence: score,
      };
    }
    if (candidate.decision === "pending") {
      return {
        type: candidateType(candidate),
        badge: "需要确认",
        decision: "结构像控件，但证据尚不足以直接建议保留",
        why: reasons.slice(-3).join("；") || "检测到控件结构，但置信度处于人工确认区间。",
        suggestion: "进入专业审核，确认视觉范围与实际点击热区是否一致。",
        confidence: score,
      };
    }
    return {
      type: candidateType(candidate),
      badge: "建议保留",
      decision: "多个现有视觉规则支持这是可点击区域",
      why: reasons.slice(-3).join("；") || "轮廓、尺寸和位置符合可交互区域特征。",
      suggestion: "建议保留为 candidate，并由人工确认 visual_bbox 与 hit_bbox。",
      confidence: score,
    };
  }

  function buildSummary(payload, items) {
    const diagnostics = payload?.report?.diagnostics || {};
    const keep = items.filter((item) => item.decision === "keep").length;
    const pending = items.filter((item) => item.decision === "pending").length;
    const ignored = items.filter((item) => item.decision === "ignored").length;
    const initial = Number(diagnostics.visual_candidate_count || keep + pending + ignored);
    const activeRegion = diagnostics.active_region || null;
    return {
      keep,
      pending,
      ignored,
      initial,
      final: keep + pending,
      activeRegion,
      text: `从 ${initial} 个初始候选中形成 ${keep + pending} 个最终建议，其中 ${pending} 个需要人工确认。`,
      pageState: activeRegion
        ? "当前页面检测到活动区域；背景层和活动层容器已按现有规则排除。"
        : "当前页面未检测到需要隔离背景控件的活动层。",
    };
  }

  const api = Object.freeze({ buildResultItems, buildSummary, candidateType, explainCandidate, reasonLabel });
  if (typeof window !== "undefined") {
    window.JingweiMomentRules = api;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})();
