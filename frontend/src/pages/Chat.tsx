import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, Progress, SessionDetail, track } from "../api/client";

interface Msg {
  role: string;
  content: string;
}

const QUICK_REPLIES = ["没做过", "说不上来"];

export default function Chat() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [ended, setEnded] = useState(false);
  const [reportId, setReportId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [resumed, setResumed] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      try {
        const detail = await api.get<SessionDetail>(`/api/sessions/${sessionId}`);
        setMessages(detail.messages.map((m) => ({ role: m.role, content: m.content })));
        setProgress(detail.progress);
        if (detail.status !== "active" && detail.status !== "wrapping") {
          setEnded(true);
          setReportId(detail.report_id);
        } else if (detail.messages.length > 1) {
          setResumed(true); // 续聊：下一条消息带 resumed，AI 会先回放要点
          track("session_resume", sessionId);
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) navigate("/auth");
        else setError("加载失败，请刷新重试");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  async function send(text: string) {
    if (!text.trim() || sending || ended) return;
    setError("");
    setSending(true);
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    try {
      const resp = await api.post<{
        message: string;
        progress: Progress;
        ended: boolean;
        report_id?: string;
      }>(`/api/sessions/${sessionId}/messages`, { content: text, resumed });
      setResumed(false);
      setMessages((m) => [...m, { role: "assistant", content: resp.message }]);
      setProgress(resp.progress);
      if (resp.ended) {
        setEnded(true);
        if (resp.report_id) setReportId(resp.report_id);
      }
    } catch (err) {
      setMessages((m) => m.slice(0, -1));
      setInput(text);
      setError(err instanceof ApiError ? err.message : "发送失败，请重试");
    } finally {
      setSending(false);
    }
  }

  async function endSession() {
    if (!confirm("确定现在结束吗？已聊到的内容会生成报告，没覆盖的维度将标注「待核实」。")) return;
    try {
      const resp = await api.post<{ report_id: string }>(`/api/sessions/${sessionId}/end`);
      setEnded(true);
      setReportId(resp.report_id);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: "好的，我们就聊到这里。报告马上开始生成，通常 2–3 分钟。",
        },
      ]);
    } catch {
      setError("结束失败，请重试");
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  const doneCount = progress?.dimensions.filter((d) => d.done).length ?? 0;

  return (
    <div className="mx-auto flex h-dvh max-w-3xl flex-col px-4">
      <header className="flex items-center justify-between border-b border-line py-3">
        <div>
          <Link to="/dashboard" className="text-xs text-gray-400 hover:text-navy">
            ← 控制台
          </Link>
          <div className="flex items-center gap-2">
            <span className="font-bold text-navy">AI 诊断师</span>
            <span className="rounded border border-brand-orange px-1.5 py-0.5 text-[10px] font-bold text-brand-orange">
              AI
            </span>
          </div>
        </div>
        {!ended && (
          <button
            onClick={endSession}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-gray-500 hover:border-brand-orange hover:text-brand-orange"
          >
            结束诊断
          </button>
        )}
      </header>

      {progress && (
        <div className="border-b border-line py-2">
          <div className="flex items-center gap-1.5 overflow-x-auto text-[11px]">
            <span className="shrink-0 font-bold text-gray-400">{doneCount}/7</span>
            {progress.dimensions.map((d) => (
              <span
                key={d.key}
                className={`shrink-0 rounded-full px-2 py-0.5 ${
                  d.done
                    ? "bg-brand-blue text-white"
                    : d.key === progress.current_dimension
                      ? "bg-peach text-brand-orange ring-1 ring-brand-orange"
                      : d.questions_asked > 0
                        ? "bg-card text-brand-blue"
                        : "bg-soft text-gray-400"
                }`}
              >
                {d.short}
              </span>
            ))}
          </div>
        </div>
      )}

      <main className="flex-1 space-y-4 overflow-y-auto py-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-[15px] leading-7 ${
                m.role === "user"
                  ? "rounded-br-md bg-brand-blue text-white"
                  : "rounded-bl-md bg-soft text-ink"
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-md bg-soft px-4 py-2.5 text-sm text-gray-400">
              正在思考…
            </div>
          </div>
        )}
        {ended && (
          <div className="rounded-xl bg-peach p-4 text-center text-sm">
            <p className="font-medium text-navy">诊断已结束，报告正在后台生成（通常 2–3 分钟）</p>
            {reportId && (
              <Link
                to={`/report/${reportId}`}
                className="mt-2 inline-block rounded-lg bg-brand-orange px-5 py-2 font-bold text-white"
              >
                查看生成进度 →
              </Link>
            )}
            <p className="mt-2 text-xs text-gray-400">也可以先离开，稍后在控制台查看结果。</p>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      {!ended && (
        <footer className="border-t border-line py-3">
          {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
          <div className="mb-2 flex gap-2">
            {QUICK_REPLIES.map((q) => (
              <button
                key={q}
                onClick={() => send(q)}
                disabled={sending}
                className="rounded-full border border-line px-3 py-1 text-xs text-gray-500 hover:border-brand-blue hover:text-brand-blue disabled:opacity-40"
              >
                {q}
              </button>
            ))}
            <span className="ml-auto self-center text-[11px] text-gray-300">
              答不上来也是有效信息
            </span>
          </div>
          <form onSubmit={submit} className="flex gap-2">
            <textarea
              className="max-h-32 flex-1 resize-none rounded-xl border border-line px-4 py-2.5 text-[15px] outline-none focus:border-brand-blue"
              rows={1}
              placeholder="口语化回答就行…（Enter 发送，Shift+Enter 换行）"
              value={input}
              maxLength={2000}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
            />
            <button
              disabled={sending || !input.trim()}
              className="rounded-xl bg-brand-blue px-5 font-bold text-white disabled:opacity-40"
            >
              发送
            </button>
          </form>
        </footer>
      )}
    </div>
  );
}
