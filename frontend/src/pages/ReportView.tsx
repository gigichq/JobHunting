import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, ReportBrief, track } from "../api/client";

const STAGE_ORDER = ["extracting", "verifying", "scoring", "concluding", "composing", "rendering"];

export default function ReportView() {
  const { reportId } = useParams<{ reportId: string }>();
  const [report, setReport] = useState<ReportBrief | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const [showCorrection, setShowCorrection] = useState(false);
  const [correctionFact, setCorrectionFact] = useState("");
  const [correctionComment, setCorrectionComment] = useState("");
  const [correctionDone, setCorrectionDone] = useState(false);
  const [error, setError] = useState("");
  const viewTracked = useRef(false);
  const navigate = useNavigate();

  const poll = useCallback(async () => {
    try {
      const r = await api.get<ReportBrief>(`/api/reports/${reportId}/status`);
      setReport(r);
      return r;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) navigate("/auth");
      return null;
    }
  }, [reportId, navigate]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    async function loop() {
      const r = await poll();
      if (stopped) return;
      if (r && (r.status === "ready" || r.status === "degraded")) {
        const content = await api.get<string>(`/api/reports/${reportId}/html`);
        if (!stopped) {
          setHtml(content);
          if (!viewTracked.current) {
            viewTracked.current = true;
            track("report_view", r.session_id);
          }
        }
        return;
      }
      timer = setTimeout(loop, 2000); // 2s 轮询
    }
    loop();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId]);

  async function retry() {
    setError("");
    try {
      await api.post(`/api/reports/${reportId}/retry`);
      await poll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "重试失败");
    }
  }

  async function sendFeedback(helpful: boolean, actionable: boolean) {
    await api.post(`/api/reports/${reportId}/feedback`, { helpful, actionable });
    setFeedbackSent(true);
  }

  async function submitCorrection() {
    if (!correctionFact.trim() || !correctionComment.trim()) return;
    await api.post(`/api/reports/${reportId}/correction`, {
      quote_or_fact: correctionFact,
      comment: correctionComment,
    });
    setCorrectionDone(true);
  }

  // ---- 生成中 / 失败 ----
  if (!html) {
    const stageIdx = report?.progress_stage ? STAGE_ORDER.indexOf(report.progress_stage) : -1;
    return (
      <div className="mx-auto max-w-xl px-4 py-16 text-center">
        <Link to="/dashboard" className="text-sm text-gray-400 hover:text-navy">
          ← 返回控制台
        </Link>
        {report?.status === "failed" ? (
          <div className="mt-8 rounded-2xl border border-line p-8">
            <div className="text-lg font-bold text-navy">生成遇到了问题</div>
            <p className="mt-2 text-sm text-gray-500">{report.error}</p>
            <p className="mt-1 text-xs text-gray-400">你的对话已保存，重试无需重新对话。</p>
            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
            <button
              onClick={retry}
              className="mt-4 rounded-lg bg-brand-orange px-6 py-2.5 font-bold text-white"
            >
              一键重试（从断点继续）
            </button>
          </div>
        ) : (
          <div className="mt-8 rounded-2xl border border-line p-8">
            <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-line border-t-brand-orange" />
            <div className="mt-4 text-lg font-bold text-navy">报告生成中</div>
            <p className="mt-1 text-sm text-gray-500">
              {report?.progress_text || "准备中…"}
            </p>
            <div className="mx-auto mt-4 flex max-w-xs gap-1">
              {STAGE_ORDER.map((s, i) => (
                <div
                  key={s}
                  className={`h-1.5 flex-1 rounded-full ${
                    i <= stageIdx ? "bg-brand-orange" : "bg-line"
                  }`}
                />
              ))}
            </div>
            <p className="mt-4 text-xs text-gray-400">
              通常 2–3 分钟。可以先离开，回控制台随时查看结果。
            </p>
            {report?.can_retry && (
              <button onClick={retry} className="mt-3 text-sm text-brand-blue underline">
                等太久了？一键重试
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  // ---- 报告就绪 ----
  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center justify-between gap-2 border-b border-line bg-white px-4 py-2.5">
        <Link to="/dashboard" className="shrink-0 text-sm text-gray-400 hover:text-navy">
          ← 控制台
        </Link>
        <div className="flex items-center gap-2 text-sm">
          {report?.status === "degraded" && (
            <span className="rounded bg-peach px-2 py-1 text-xs text-brand-orange">
              简版交付 · 可重试完整报告
            </span>
          )}
          <button
            onClick={() => setShowCorrection(true)}
            className="rounded-lg border border-line px-3 py-1.5 text-gray-500 hover:text-navy"
          >
            内容与事实不符？
          </button>
          <a
            href={`/api/reports/${reportId}/download`}
            onClick={() => track("report_download", report?.session_id)}
            className="rounded-lg bg-brand-blue px-4 py-1.5 font-bold text-white"
          >
            下载报告
          </a>
        </div>
      </header>

      <iframe title="诊断报告" srcDoc={html} className="w-full flex-1 border-0" />

      {!feedbackSent ? (
        <footer className="border-t border-line bg-soft px-4 py-3">
          <div className="mx-auto flex max-w-2xl flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm">
            <span className="font-medium text-navy">这份报告对你有帮助吗？有没有找到能立刻执行的下一步？</span>
            <div className="flex gap-2">
              <button
                onClick={() => sendFeedback(true, true)}
                className="rounded-lg bg-brand-blue px-3 py-1.5 text-white"
              >
                👍 有帮助，找到了
              </button>
              <button
                onClick={() => sendFeedback(true, false)}
                className="rounded-lg border border-line bg-white px-3 py-1.5"
              >
                有帮助，但没找到下一步
              </button>
              <button
                onClick={() => sendFeedback(false, false)}
                className="rounded-lg border border-line bg-white px-3 py-1.5"
              >
                👎 没帮助
              </button>
            </div>
          </div>
        </footer>
      ) : (
        <footer className="border-t border-line bg-soft px-4 py-2 text-center text-xs text-gray-400">
          谢谢反馈！记得下载保存报告（测试版数据可能随更新清除）。
        </footer>
      )}

      {showCorrection && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6">
            {correctionDone ? (
              <>
                <h3 className="font-bold text-navy">已收到你的纠错</h3>
                <p className="mt-2 text-sm text-gray-500">
                  我们会在 72 小时内对照对话原文人工核实；核实成立会重算受影响的维度并发布新版本报告。
                </p>
                <button
                  onClick={() => setShowCorrection(false)}
                  className="mt-4 w-full rounded-lg bg-brand-blue py-2 font-bold text-white"
                >
                  好的
                </button>
              </>
            ) : (
              <>
                <h3 className="font-bold text-navy">内容与事实不符？告诉我们</h3>
                <input
                  className="mt-3 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-brand-blue"
                  placeholder="报告中哪句话/哪个事实不符？（可直接粘贴）"
                  value={correctionFact}
                  maxLength={1000}
                  onChange={(e) => setCorrectionFact(e.target.value)}
                />
                <textarea
                  className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-brand-blue"
                  rows={3}
                  placeholder="实际情况是…"
                  value={correctionComment}
                  maxLength={1000}
                  onChange={(e) => setCorrectionComment(e.target.value)}
                />
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={() => setShowCorrection(false)}
                    className="flex-1 rounded-lg border border-line py-2 text-gray-500"
                  >
                    取消
                  </button>
                  <button
                    onClick={submitCorrection}
                    className="flex-1 rounded-lg bg-brand-orange py-2 font-bold text-white"
                  >
                    提交纠错
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
