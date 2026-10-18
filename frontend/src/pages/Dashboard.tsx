import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, SessionBrief, User } from "../api/client";

const STATUS_TEXT: Record<string, string> = {
  active: "进行中 · 可继续",
  wrapping: "收尾中",
  ended: "已结束",
  generating: "报告生成中",
  report_ready: "报告已就绪",
  failed: "生成失败 · 可重试",
};

export default function Dashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [sessions, setSessions] = useState<SessionBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  async function load() {
    try {
      const [me, list] = await Promise.all([
        api.get<User>("/api/auth/me"),
        api.get<SessionBrief[]>("/api/sessions"),
      ]);
      setUser(me);
      setSessions(list);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) navigate("/auth");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function logout() {
    await api.post("/api/auth/logout");
    navigate("/");
  }

  async function removeSession(id: string) {
    if (!confirm("删除这次诊断？对话与报告将一并删除，不可恢复。")) return;
    await api.delete(`/api/sessions/${id}`);
    load();
  }

  async function deleteAccount() {
    if (!confirm("确定删除账号？所有诊断、对话与报告将永久删除。")) return;
    if (!confirm("再次确认：此操作不可恢复。")) return;
    await api.delete("/api/auth/me");
    navigate("/");
  }

  if (loading) return <div className="p-10 text-center text-gray-400">加载中…</div>;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <header className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold tracking-[0.3em] text-brand-orange">求职陪跑</div>
          <h1 className="mt-1 text-xl font-bold text-navy">你好，{user?.display_name}</h1>
        </div>
        <button onClick={logout} className="text-sm text-gray-400 hover:text-navy">
          退出登录
        </button>
      </header>

      <Link
        to="/new"
        className="mt-6 block rounded-2xl bg-gradient-to-br from-navy to-[#142b52] p-6 text-white transition hover:brightness-110"
      >
        <div className="text-lg font-bold">＋ 新建诊断</div>
        <div className="mt-1 text-sm text-[#b9c6e8]">
          快速档约 20 分钟 / 完整档约 40–60 分钟 · 任何时刻结束都能出报告
        </div>
      </Link>

      <h2 className="mt-8 text-sm font-bold text-gray-500">我的诊断</h2>
      {sessions.length === 0 && (
        <p className="mt-3 text-sm text-gray-400">还没有诊断记录，从上面的按钮开始吧。</p>
      )}
      <div className="mt-3 space-y-3">
        {sessions.map((s) => (
          <div key={s.id} className="rounded-xl border border-line p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="font-semibold text-navy">
                  {s.mode === "quick" ? "快速诊断" : "完整诊断"}
                </span>
                <span className="ml-2 text-xs text-gray-400">
                  {new Date(s.created_at).toLocaleString("zh-CN")} ·{" "}
                  {s.identity === "student" ? "学生" : "职场人"}
                </span>
                <div className="mt-1 text-sm text-gray-500">
                  {STATUS_TEXT[s.status] ?? s.status} · 已问 {s.turn_count} 轮
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-sm">
                {(s.status === "active" || s.status === "wrapping") && (
                  <Link
                    to={`/chat/${s.id}`}
                    className="rounded-lg bg-brand-blue px-3 py-1.5 font-medium text-white"
                  >
                    继续
                  </Link>
                )}
                {s.report_id && (
                  <Link
                    to={`/report/${s.report_id}`}
                    className="rounded-lg bg-brand-orange px-3 py-1.5 font-medium text-white"
                  >
                    {s.report_status === "ready" || s.report_status === "degraded"
                      ? "看报告"
                      : "报告进度"}
                  </Link>
                )}
                <button
                  onClick={() => removeSession(s.id)}
                  className="text-gray-300 hover:text-red-500"
                  title="删除"
                >
                  ✕
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <footer className="mt-16 border-t border-line pt-4 text-xs text-gray-400">
        <button onClick={deleteAccount} className="underline hover:text-red-500">
          删除我的账号与全部数据
        </button>
        <p className="mt-2">测试版：数据可能随服务更新清除，报告生成后请及时下载保存。</p>
      </footer>
    </div>
  );
}
