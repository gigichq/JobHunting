import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, User } from "../api/client";

export default function Auth() {
  const [mode, setMode] = useState<"login" | "register">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "register") {
        await api.post<User>("/api/auth/register", {
          email,
          password,
          display_name: displayName,
          age_confirmed: ageConfirmed,
        });
      } else {
        await api.post<User>("/api/auth/login", { email, password });
      }
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "网络异常，请重试");
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded-lg border border-line px-4 py-2.5 text-sm outline-none focus:border-brand-blue";

  return (
    <div className="flex min-h-screen items-center justify-center bg-soft px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-sm">
        <Link to="/" className="text-xs font-semibold tracking-[0.3em] text-brand-orange">
          求职陪跑
        </Link>
        <h1 className="mt-2 text-xl font-bold text-navy">
          {mode === "register" ? "注册，开始你的诊断" : "欢迎回来"}
        </h1>

        <div className="mt-4 flex gap-1 rounded-lg bg-soft p-1 text-sm font-medium">
          {(["register", "login"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex-1 rounded-md py-1.5 transition ${
                mode === m ? "bg-white text-navy shadow-sm" : "text-gray-400"
              }`}
            >
              {m === "register" ? "注册" : "登录"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="mt-5 space-y-3">
          <input
            className={input}
            type="email"
            placeholder="邮箱"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            className={input}
            type="password"
            placeholder={mode === "register" ? "密码（至少 8 位）" : "密码"}
            value={password}
            minLength={mode === "register" ? 8 : undefined}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {mode === "register" && (
            <>
              <input
                className={input}
                placeholder="怎么称呼你？（支持化名）"
                value={displayName}
                maxLength={32}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
              <label className="flex items-start gap-2 text-xs leading-5 text-gray-500">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={ageConfirmed}
                  onChange={(e) => setAgeConfirmed(e.target.checked)}
                  required
                />
                <span>
                  我已年满 18 周岁。我了解：对话内容将用于生成我的诊断报告，并通过 AI
                  网关调用第三方大模型处理；支持用化名和公司脱敏完成诊断，不影响报告质量；
                  账号与诊断随时可删除。
                </span>
              </label>
            </>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            disabled={busy}
            className="w-full rounded-lg bg-brand-blue py-2.5 font-bold text-white transition hover:brightness-110 disabled:opacity-50"
          >
            {busy ? "请稍候…" : mode === "register" ? "注册并开始" : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}
