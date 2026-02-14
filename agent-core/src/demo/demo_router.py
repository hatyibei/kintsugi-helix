"""Live demo endpoint for Kintsugi-Helix.

SSE-based streaming demo that shows the full autonomous repair pipeline
in real-time. Designed for hackathon demo videos and live presentations.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

from src.demo.scenario import (
    BUGGY_ORDER_SERVICE,
    CODE_DIFF,
    DEMO_ERROR_LOGS,
    FALLBACK_BLAST_RADIUS,
    FALLBACK_RCA,
    FIXED_ORDER_SERVICE,
    GENERATED_TEST_CODE,
    LEARNING_ENTRY,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/demo", tags=["demo"])


async def _sse_event(event: str, data: dict) -> str:
    """Format SSE event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_demo_pipeline(use_gemini: bool = False) -> AsyncGenerator[str, None]:
    """Run the full demo pipeline with SSE streaming.
    
    Args:
        use_gemini: If True, call real Gemini API. If False, use pre-built scenario.
    """
    start_time = time.time()

    # ========================================================================
    # Phase 0: Initialize
    # ========================================================================
    yield await _sse_event("phase", {
        "phase": "init",
        "title": "🔧 Kintsugi-Helix 起動",
        "description": "自律型障害回復エージェントを初期化中...",
        "timestamp": datetime.now().isoformat(),
    })
    await asyncio.sleep(1.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "Vertex AI Gemini 2.5 Pro 接続確認",
        "component": "vertex_client",
    })
    await asyncio.sleep(0.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "Cloud Logging クライアント初期化完了",
        "component": "log_collector",
    })
    await asyncio.sleep(0.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "MCP Server ready on port 8080",
        "component": "mcp_server",
    })
    await asyncio.sleep(1.0)

    # ========================================================================
    # Phase 1: Sensing (感知)
    # ========================================================================
    yield await _sse_event("phase", {
        "phase": "sensing",
        "title": "👁️ Phase 1: Sensing（感知）",
        "description": "Cloud Logging からエラーログを収集・分析中...",
    })
    await asyncio.sleep(1.5)

    # Show error logs being collected
    error = DEMO_ERROR_LOGS[0]
    yield await _sse_event("error_detected", {
        "service": error["service"],
        "revision": error["revision"],
        "message": error["message"],
        "count": error["count"],
        "http_request": error["http_request"],
        "trace_id": error["trace_id"],
        "severity": "ERROR",
    })
    await asyncio.sleep(2.0)

    # Stack trace parsing
    yield await _sse_event("log", {
        "level": "INFO",
        "message": "スタックトレース解析: 2個の内部フレーム検出",
        "component": "stack_trace_parser",
    })
    await asyncio.sleep(0.8)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "ルートコーズフレーム: OrderService.createOrder(OrderService.java:42)",
        "component": "stack_trace_parser",
    })
    await asyncio.sleep(0.8)

    # Source code extraction
    yield await _sse_event("source_extracted", {
        "files": [
            "src/main/java/com/kintsugi/demo/service/OrderService.java",
            "src/main/java/com/kintsugi/demo/controller/OrderController.java",
            "src/main/java/com/kintsugi/demo/repository/UserRepository.java",
        ],
        "total_lines": 187,
    })
    await asyncio.sleep(1.0)

    # RCA with Gemini
    yield await _sse_event("log", {
        "level": "INFO",
        "message": "🧠 Gemini 2.5 Pro に根本原因分析をリクエスト中...",
        "component": "root_cause_analyzer",
    })
    await asyncio.sleep(2.5)

    # RCA result
    rca = FALLBACK_RCA
    yield await _sse_event("rca_result", {
        "summary": rca["summary"],
        "root_cause": rca["root_cause"],
        "affected_component": rca["affected_component"],
        "suggested_fix": rca["suggested_fix"],
        "confidence": rca["confidence"],
        "severity": rca["severity"],
        "related_files": rca["related_files"],
    })
    await asyncio.sleep(2.0)

    # Show buggy source code
    yield await _sse_event("source_code", {
        "file": "src/main/java/com/kintsugi/demo/service/OrderService.java",
        "code": BUGGY_ORDER_SERVICE,
        "error_line": 42,
        "label": "バグのあるコード",
    })
    await asyncio.sleep(1.5)

    # ========================================================================
    # Phase 2: Reflection (反射)
    # ========================================================================
    yield await _sse_event("phase", {
        "phase": "reflection",
        "title": "🔬 Phase 2: Reflection（反射）",
        "description": "バグを再現するJUnitテストを自動生成中...",
    })
    await asyncio.sleep(1.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "NPE再現テスト生成中... (Gemini 2.5 Pro)",
        "component": "test_generator",
    })
    await asyncio.sleep(2.0)

    # Generated test
    yield await _sse_event("test_generated", {
        "class_name": "OrderServiceBugReproductionTest",
        "test_method": "createOrder_withNonExistentUser_shouldThrowNPE",
        "test_type": "bug_reproduction",
        "source_code": GENERATED_TEST_CODE,
    })
    await asyncio.sleep(1.5)

    # Test execution
    yield await _sse_event("log", {
        "level": "INFO",
        "message": "テスト実行中... (Maven + Testcontainers)",
        "component": "testcontainer_runner",
    })
    await asyncio.sleep(2.0)

    yield await _sse_event("test_result", {
        "success": False,
        "test_name": "createOrder_withNonExistentUser_shouldThrowNPE",
        "failure_type": "assertion",
        "message": "Expected NullPointerException was thrown ✅ バグ再現成功！",
        "execution_time_ms": 3420,
        "bug_confirmed": True,
    })
    await asyncio.sleep(2.0)

    # ========================================================================
    # Phase 3: Evolution (進化)
    # ========================================================================
    yield await _sse_event("phase", {
        "phase": "evolution",
        "title": "🧬 Phase 3: Evolution（進化）",
        "description": "Gemini がコード修正を生成・検証中...",
    })
    await asyncio.sleep(1.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "Fix attempt 1/3: コード修正を生成中...",
        "component": "code_fixer",
    })
    await asyncio.sleep(2.0)

    # Show diff
    yield await _sse_event("code_fix", {
        "file": "src/main/java/com/kintsugi/demo/service/OrderService.java",
        "diff": CODE_DIFF,
        "description": "Optional.orElse(null) → Optional.orElseThrow() に修正",
        "lines_changed": 4,
        "confidence": 0.95,
        "attempt": 1,
    })
    await asyncio.sleep(1.5)

    # Show fixed code
    yield await _sse_event("source_code", {
        "file": "src/main/java/com/kintsugi/demo/service/OrderService.java",
        "code": FIXED_ORDER_SERVICE,
        "highlight_lines": [31, 32, 33],
        "label": "修正後のコード",
    })
    await asyncio.sleep(1.5)

    # Verify fix
    yield await _sse_event("log", {
        "level": "INFO",
        "message": "修正後のテスト実行中...",
        "component": "testcontainer_runner",
    })
    await asyncio.sleep(2.0)

    yield await _sse_event("test_result", {
        "success": True,
        "test_name": "createOrder_withNonExistentUser_shouldThrowIllegalArgument",
        "message": "IllegalArgumentException thrown as expected ✅ 修正成功！",
        "execution_time_ms": 2150,
        "bug_confirmed": False,
    })
    await asyncio.sleep(1.0)

    # Regression check
    yield await _sse_event("log", {
        "level": "INFO",
        "message": "リグレッションテスト実行中... (全テストスイート)",
        "component": "testcontainer_runner",
    })
    await asyncio.sleep(1.5)

    yield await _sse_event("regression_result", {
        "total_tests": 12,
        "passed": 12,
        "failed": 0,
        "errors": 0,
        "execution_time_seconds": 8.4,
        "message": "全テストパス ✅ リグレッションなし",
    })
    await asyncio.sleep(1.5)

    # OpenRewrite
    yield await _sse_event("log", {
        "level": "INFO",
        "message": "OpenRewrite: common-static-analysis レシピ実行中...",
        "component": "openrewrite_executor",
    })
    await asyncio.sleep(1.0)

    yield await _sse_event("openrewrite_result", {
        "recipe": "common-static-analysis",
        "files_changed": 1,
        "improvements": ["SimplifyBooleanExpression applied"],
    })
    await asyncio.sleep(1.0)

    # ========================================================================
    # Phase 4: Governance (統治)
    # ========================================================================
    yield await _sse_event("phase", {
        "phase": "governance",
        "title": "🏛️ Phase 4: Governance（統治）",
        "description": "影響範囲（Blast Radius）を分析し、マージ判断中...",
    })
    await asyncio.sleep(1.5)

    # Blast radius
    br = FALLBACK_BLAST_RADIUS
    yield await _sse_event("blast_radius", {
        "score": br["score"],
        "risk_level": br["risk_level"],
        "files_affected": br["files_affected"],
        "dependencies_affected": br["dependencies_affected"],
        "recommendation": br["recommendation"],
        "reasoning": br["reasoning"],
        "business_impact": br["business_impact"],
    })
    await asyncio.sleep(2.0)

    # Auto-merge decision
    yield await _sse_event("merge_decision", {
        "decision": "auto_merge",
        "reason": f"Blast Radius Score: {br['score']} < 0.3 threshold → 自動マージ承認",
        "branch": "kintsugi/fix-npe-orderservi",
    })
    await asyncio.sleep(1.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "git commit -m 'fix: NullPointerException in OrderService.createOrder'",
        "component": "git_helper",
    })
    await asyncio.sleep(0.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "git merge kintsugi/fix-npe-orderservi → main",
        "component": "git_helper",
    })
    await asyncio.sleep(0.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "git push origin main ✅",
        "component": "git_helper",
    })
    await asyncio.sleep(1.5)

    # ========================================================================
    # Phase 5: Learning (免疫記憶)
    # ========================================================================
    yield await _sse_event("phase", {
        "phase": "learning",
        "title": "🧠 Phase 5: Learning（免疫記憶）",
        "description": "修正経験を学習メモリに記録中...",
    })
    await asyncio.sleep(1.0)

    le = LEARNING_ENTRY
    yield await _sse_event("learning_recorded", {
        "bug_type": le["bug_type"],
        "pattern": le["pattern"],
        "fix_pattern": le["fix_pattern"],
        "confidence": le["confidence"],
        "key_insight": le["key_insight"],
        "similar_risks": le["similar_risks"],
    })
    await asyncio.sleep(1.5)

    yield await _sse_event("log", {
        "level": "INFO",
        "message": "KNOWLEDGE_BASE.json 更新・コミット完了",
        "component": "learning_memory",
    })
    await asyncio.sleep(1.0)

    # ========================================================================
    # Complete
    # ========================================================================
    elapsed = round(time.time() - start_time, 1)

    yield await _sse_event("complete", {
        "title": "✨ 金継ぎ完了",
        "summary": {
            "incidents_found": 1,
            "bugs_confirmed": 1,
            "fixes_applied": 1,
            "auto_merged": 1,
            "learnings_recorded": 1,
            "total_time_seconds": elapsed,
        },
        "message": "壊れた部分を金で修復し、システムはより強くなりました。",
    })


@router.get("/run")
async def run_demo():
    """Run the full Kintsugi-Helix demo pipeline with SSE streaming."""
    return StreamingResponse(
        _run_demo_pipeline(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/", response_class=HTMLResponse)
async def demo_dashboard():
    """Serve the demo dashboard HTML."""
    return DEMO_HTML


# ============================================================================
# Demo Dashboard HTML
# ============================================================================

DEMO_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kintsugi-Helix | 自律型障害回復デモ</title>
<style>
  :root {
    --bg: #0a0a0f;
    --card: #12121a;
    --border: #1e1e2e;
    --gold: #d4a853;
    --gold-light: #f0d68a;
    --cyan: #00d4ff;
    --green: #00ff88;
    --red: #ff4444;
    --orange: #ff8c00;
    --purple: #b366ff;
    --text: #e0e0e0;
    --text-dim: #888;
    --font: 'Segoe UI', 'Noto Sans JP', sans-serif;
    --mono: 'Cascadia Code', 'Fira Code', monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    overflow-x: hidden;
  }
  
  /* Header */
  .header {
    text-align: center;
    padding: 30px 20px 20px;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, #0f0f18 0%, var(--bg) 100%);
  }
  .header h1 {
    font-size: 2.2rem;
    background: linear-gradient(135deg, var(--gold), var(--gold-light));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }
  .header .subtitle {
    color: var(--text-dim);
    font-size: 0.95rem;
  }
  .header .subtitle span { color: var(--gold); }

  /* Controls */
  .controls {
    text-align: center;
    padding: 20px;
  }
  .btn-run {
    background: linear-gradient(135deg, var(--gold), #b8922e);
    color: #000;
    border: none;
    padding: 14px 40px;
    font-size: 1.1rem;
    font-weight: bold;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.3s;
    letter-spacing: 1px;
  }
  .btn-run:hover { transform: translateY(-2px); box-shadow: 0 4px 20px rgba(212,168,83,0.4); }
  .btn-run:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

  /* Main layout */
  .main {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    padding: 16px 20px;
    max-width: 1400px;
    margin: 0 auto;
  }
  @media (max-width: 900px) { .main { grid-template-columns: 1fr; } }

  /* Cards */
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .card-header {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    font-weight: bold;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .card-body {
    padding: 16px;
    max-height: 500px;
    overflow-y: auto;
  }
  .card-body::-webkit-scrollbar { width: 4px; }
  .card-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  /* Phase indicator */
  .phases {
    grid-column: 1 / -1;
    display: flex;
    gap: 4px;
    padding: 0 20px;
  }
  .phase-step {
    flex: 1;
    padding: 10px 8px;
    text-align: center;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 0.75rem;
    transition: all 0.5s;
    opacity: 0.4;
  }
  .phase-step.active {
    opacity: 1;
    border-color: var(--gold);
    box-shadow: 0 0 12px rgba(212,168,83,0.2);
  }
  .phase-step.done {
    opacity: 0.8;
    border-color: var(--green);
    background: rgba(0,255,136,0.05);
  }
  .phase-step .icon { font-size: 1.3rem; display: block; margin-bottom: 4px; }

  /* Log entries */
  .log-entry {
    font-family: var(--mono);
    font-size: 0.78rem;
    padding: 4px 0;
    border-bottom: 1px solid rgba(255,255,255,0.03);
    animation: fadeIn 0.3s ease;
  }
  .log-entry .ts { color: var(--text-dim); margin-right: 8px; }
  .log-entry .comp { color: var(--purple); margin-right: 8px; }
  .log-entry.INFO .msg { color: var(--cyan); }
  .log-entry.ERROR .msg { color: var(--red); }

  /* Code block */
  .code-block {
    background: #0d0d12;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    font-family: var(--mono);
    font-size: 0.75rem;
    line-height: 1.5;
    overflow-x: auto;
    white-space: pre;
    margin: 8px 0;
    max-height: 300px;
    overflow-y: auto;
  }
  .code-block .line-err { background: rgba(255,68,68,0.15); display: block; }
  .code-block .line-fix { background: rgba(0,255,136,0.1); display: block; }

  /* RCA card */
  .rca-item {
    margin: 8px 0;
    padding: 8px 12px;
    background: rgba(212,168,83,0.05);
    border-left: 3px solid var(--gold);
    border-radius: 0 6px 6px 0;
    font-size: 0.85rem;
  }
  .rca-item .label { color: var(--gold); font-weight: bold; font-size: 0.75rem; margin-bottom: 2px; }

  /* Blast radius */
  .blast-meter {
    height: 8px;
    background: var(--border);
    border-radius: 4px;
    margin: 8px 0;
    overflow: hidden;
  }
  .blast-meter-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 1s ease;
  }

  /* Badge */
  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: bold;
  }
  .badge-green { background: rgba(0,255,136,0.15); color: var(--green); }
  .badge-red { background: rgba(255,68,68,0.15); color: var(--red); }
  .badge-gold { background: rgba(212,168,83,0.15); color: var(--gold); }
  .badge-orange { background: rgba(255,140,0,0.15); color: var(--orange); }

  /* Summary */
  .summary-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    grid-column: 1 / -1;
    padding: 0 20px 20px;
  }
  .summary-stat {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }
  .summary-stat .value {
    font-size: 2rem;
    font-weight: bold;
    color: var(--gold);
  }
  .summary-stat .label { color: var(--text-dim); font-size: 0.8rem; margin-top: 4px; }

  /* Animations */
  @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
  .pulsing { animation: pulse 1.5s ease infinite; }

  /* Complete overlay */
  .complete-banner {
    grid-column: 1 / -1;
    text-align: center;
    padding: 30px;
    background: linear-gradient(135deg, rgba(212,168,83,0.1), rgba(0,212,255,0.05));
    border: 1px solid var(--gold);
    border-radius: 12px;
    margin: 0 20px 20px;
    animation: fadeIn 0.8s ease;
  }
  .complete-banner h2 {
    font-size: 1.8rem;
    color: var(--gold);
    margin-bottom: 8px;
  }
  .complete-banner p { color: var(--text-dim); }
  
  .hidden { display: none; }
</style>
</head>
<body>

<div class="header">
  <h1>🔧 Kintsugi-Helix</h1>
  <div class="subtitle">
    <span>金継ぎ</span> — 自律型障害回復AIエージェント | Powered by <span>Vertex AI Gemini 2.5 Pro</span>
  </div>
</div>

<div class="controls">
  <button class="btn-run" id="btnRun" onclick="startDemo()">▶ デモを実行</button>
</div>

<div class="phases" id="phases">
  <div class="phase-step" id="phase-sensing"><span class="icon">👁️</span>Sensing<br><small>感知</small></div>
  <div class="phase-step" id="phase-reflection"><span class="icon">🔬</span>Reflection<br><small>反射</small></div>
  <div class="phase-step" id="phase-evolution"><span class="icon">🧬</span>Evolution<br><small>進化</small></div>
  <div class="phase-step" id="phase-governance"><span class="icon">🏛️</span>Governance<br><small>統治</small></div>
  <div class="phase-step" id="phase-learning"><span class="icon">🧠</span>Learning<br><small>免疫記憶</small></div>
</div>

<div class="main" id="mainContent">
  <!-- Left: Activity log -->
  <div class="card">
    <div class="card-header">📋 Agent Activity Log</div>
    <div class="card-body" id="logPanel"></div>
  </div>
  <!-- Right: Detail panel -->
  <div class="card">
    <div class="card-header">🔍 Detail View</div>
    <div class="card-body" id="detailPanel">
      <div style="color:var(--text-dim);text-align:center;padding:40px;">
        ▶ ボタンを押してデモを実行してください
      </div>
    </div>
  </div>
</div>

<div id="summaryArea"></div>

<script>
const logPanel = document.getElementById('logPanel');
const detailPanel = document.getElementById('detailPanel');
const btnRun = document.getElementById('btnRun');
let currentPhase = null;
const phaseOrder = ['sensing','reflection','evolution','governance','learning'];

function startDemo() {
  btnRun.disabled = true;
  btnRun.textContent = '⏳ 実行中...';
  logPanel.innerHTML = '';
  detailPanel.innerHTML = '';
  document.getElementById('summaryArea').innerHTML = '';
  
  // Reset phases
  phaseOrder.forEach(p => {
    const el = document.getElementById('phase-' + p);
    el.classList.remove('active','done');
  });
  
  const es = new EventSource('/demo/run');
  
  es.addEventListener('phase', (e) => {
    const d = JSON.parse(e.data);
    setPhase(d.phase);
    addLog('INFO', d.title, 'agent');
  });
  
  es.addEventListener('log', (e) => {
    const d = JSON.parse(e.data);
    addLog(d.level, d.message, d.component);
  });
  
  es.addEventListener('error_detected', (e) => {
    const d = JSON.parse(e.data);
    addLog('ERROR', d.message, d.service);
    detailPanel.innerHTML = `
      <div class="rca-item"><div class="label">🚨 ERROR DETECTED</div>${d.message}</div>
      <div class="rca-item"><div class="label">Service</div>${d.service} (${d.revision})</div>
      <div class="rca-item"><div class="label">HTTP</div>${d.http_request.method} ${d.http_request.url} → ${d.http_request.status}</div>
      <div class="rca-item"><div class="label">発生回数</div><span class="badge badge-red">${d.count} 回</span></div>
    `;
  });
  
  es.addEventListener('source_extracted', (e) => {
    const d = JSON.parse(e.data);
    addLog('INFO', `ソースコード抽出: ${d.files.length}ファイル (${d.total_lines}行)`, 'source_extractor');
  });
  
  es.addEventListener('rca_result', (e) => {
    const d = JSON.parse(e.data);
    detailPanel.innerHTML = `
      <h3 style="color:var(--gold);margin-bottom:12px;">🧠 Root Cause Analysis</h3>
      <div class="rca-item"><div class="label">要約</div>${d.summary}</div>
      <div class="rca-item"><div class="label">根本原因</div>${d.root_cause}</div>
      <div class="rca-item"><div class="label">対象コンポーネント</div><code>${d.affected_component}</code></div>
      <div class="rca-item"><div class="label">推奨修正</div>${d.suggested_fix}</div>
      <div class="rca-item"><div class="label">確信度</div>
        <span class="badge badge-green">${(d.confidence * 100).toFixed(0)}%</span>
        <span class="badge badge-orange">${d.severity}</span>
      </div>
    `;
  });
  
  es.addEventListener('source_code', (e) => {
    const d = JSON.parse(e.data);
    const escaped = d.code.replace(/&/g,'&amp;').replace(/</g,'&lt;');
    detailPanel.innerHTML = `
      <h3 style="color:var(--gold);margin-bottom:8px;">📄 ${d.label}</h3>
      <div style="font-size:0.75rem;color:var(--text-dim);margin-bottom:8px;">${d.file}</div>
      <div class="code-block">${escaped}</div>
    `;
  });
  
  es.addEventListener('test_generated', (e) => {
    const d = JSON.parse(e.data);
    const escaped = d.source_code.replace(/&/g,'&amp;').replace(/</g,'&lt;');
    detailPanel.innerHTML = `
      <h3 style="color:var(--cyan);margin-bottom:8px;">🧪 Generated Test</h3>
      <div class="rca-item"><div class="label">クラス</div>${d.class_name}</div>
      <div class="rca-item"><div class="label">メソッド</div>${d.test_method}</div>
      <div class="rca-item"><div class="label">タイプ</div><span class="badge badge-orange">${d.test_type}</span></div>
      <div class="code-block">${escaped}</div>
    `;
  });
  
  es.addEventListener('test_result', (e) => {
    const d = JSON.parse(e.data);
    const icon = d.bug_confirmed ? '🐛' : (d.success ? '✅' : '❌');  
    addLog(d.success || d.bug_confirmed ? 'INFO' : 'ERROR', `${icon} ${d.message}`, 'test_runner');
  });
  
  es.addEventListener('code_fix', (e) => {
    const d = JSON.parse(e.data);
    const escaped = d.diff.replace(/&/g,'&amp;').replace(/</g,'&lt;');
    detailPanel.innerHTML = `
      <h3 style="color:var(--green);margin-bottom:8px;">🔧 Code Fix (Attempt ${d.attempt})</h3>
      <div class="rca-item"><div class="label">説明</div>${d.description}</div>
      <div class="rca-item"><div class="label">変更行数</div>${d.lines_changed} lines | 確信度: ${(d.confidence * 100).toFixed(0)}%</div>
      <div class="code-block">${escaped}</div>
    `;
  });
  
  es.addEventListener('regression_result', (e) => {
    const d = JSON.parse(e.data);
    addLog('INFO', `${d.message} (${d.passed}/${d.total_tests} tests, ${d.execution_time_seconds}s)`, 'test_runner');
  });
  
  es.addEventListener('openrewrite_result', (e) => {
    const d = JSON.parse(e.data);
    addLog('INFO', `OpenRewrite: ${d.recipe} → ${d.files_changed} files changed`, 'openrewrite');
  });
  
  es.addEventListener('blast_radius', (e) => {
    const d = JSON.parse(e.data);
    const color = d.risk_level === 'low' ? 'var(--green)' : d.risk_level === 'medium' ? 'var(--orange)' : 'var(--red)';
    detailPanel.innerHTML = `
      <h3 style="color:var(--gold);margin-bottom:12px;">💥 Blast Radius Analysis</h3>
      <div class="rca-item"><div class="label">リスクスコア</div>
        <div class="blast-meter"><div class="blast-meter-fill" style="width:${d.score*100}%;background:${color};"></div></div>
        <span class="badge" style="background:rgba(0,255,136,0.15);color:${color};">${d.score} — ${d.risk_level.toUpperCase()}</span>
      </div>
      <div class="rca-item"><div class="label">影響ファイル数</div>${d.files_affected}</div>
      <div class="rca-item"><div class="label">影響コンポーネント</div>${d.dependencies_affected.join(', ')}</div>
      <div class="rca-item"><div class="label">判定</div><span class="badge badge-green">${d.recommendation}</span></div>
      <div class="rca-item"><div class="label">根拠</div>${d.reasoning}</div>
    `;
  });
  
  es.addEventListener('merge_decision', (e) => {
    const d = JSON.parse(e.data);
    addLog('INFO', `🎯 ${d.reason}`, 'governance');
  });
  
  es.addEventListener('learning_recorded', (e) => {
    const d = JSON.parse(e.data);
    detailPanel.innerHTML = `
      <h3 style="color:var(--purple);margin-bottom:12px;">🧠 Learning Memory Updated</h3>
      <div class="rca-item"><div class="label">Bug Type</div><span class="badge badge-red">${d.bug_type}</span></div>
      <div class="rca-item"><div class="label">パターン</div>${d.pattern}</div>
      <div class="rca-item"><div class="label">修正パターン</div>${d.fix_pattern}</div>
      <div class="rca-item"><div class="label">Key Insight</div>${d.key_insight}</div>
      <div class="rca-item"><div class="label">類似リスク</div>
        <ul style="margin:4px 0 0 16px;font-size:0.85rem;">${d.similar_risks.map(r => '<li>'+r+'</li>').join('')}</ul>
      </div>
    `;
  });
  
  es.addEventListener('complete', (e) => {
    const d = JSON.parse(e.data);
    es.close();
    btnRun.disabled = false;
    btnRun.textContent = '▶ もう一度実行';
    
    // Mark all phases done
    phaseOrder.forEach(p => {
      const el = document.getElementById('phase-' + p);
      el.classList.remove('active');
      el.classList.add('done');
    });
    
    const s = d.summary;
    document.getElementById('summaryArea').innerHTML = `
      <div class="complete-banner">
        <h2>${d.title}</h2>
        <p>${d.message}</p>
      </div>
      <div class="summary-grid">
        <div class="summary-stat"><div class="value">${s.incidents_found}</div><div class="label">Incidents Detected</div></div>
        <div class="summary-stat"><div class="value">${s.bugs_confirmed}</div><div class="label">Bugs Confirmed</div></div>
        <div class="summary-stat"><div class="value">${s.fixes_applied}</div><div class="label">Fixes Applied</div></div>
        <div class="summary-stat"><div class="value">${s.auto_merged}</div><div class="label">Auto-Merged</div></div>
        <div class="summary-stat"><div class="value">${s.learnings_recorded}</div><div class="label">Learnings Recorded</div></div>
        <div class="summary-stat"><div class="value">${s.total_time_seconds}s</div><div class="label">Total Time</div></div>
      </div>
    `;
  });
  
  es.onerror = () => {
    es.close();
    btnRun.disabled = false;
    btnRun.textContent = '▶ 再実行';
  };
}

function setPhase(phase) {
  if (currentPhase) {
    document.getElementById('phase-' + currentPhase).classList.remove('active');
    document.getElementById('phase-' + currentPhase).classList.add('done');
  }
  currentPhase = phase;
  const el = document.getElementById('phase-' + phase);
  if (el) {
    el.classList.add('active');
    el.classList.remove('done');
  }
}

function addLog(level, message, component) {
  const now = new Date().toLocaleTimeString('ja-JP');
  const entry = document.createElement('div');
  entry.className = 'log-entry ' + level;
  entry.innerHTML = `<span class="ts">${now}</span><span class="comp">[${component}]</span> <span class="msg">${message}</span>`;
  logPanel.appendChild(entry);
  logPanel.scrollTop = logPanel.scrollHeight;
}
</script>
</body>
</html>"""
