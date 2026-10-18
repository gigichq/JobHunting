import { useEffect } from "react";
import { Link } from "react-router-dom";
import { track } from "../api/client";

const DIMS = [
  ["01", "能力盘点", "经历是否盘成「能力—经历—成果」链条"],
  ["02", "找准岗位", "方向是比出来的，还是想出来的"],
  ["03", "商业素养", "消费者视角 vs 商业视角"],
  ["04", "专业技能", "工具零件 vs 方法链装配线"],
  ["05", "项目实践", "经历有没有复盘、闭环、可核实结果"],
  ["06", "作品集", "有没有能直接递出去的成品"],
  ["07", "投递管理", "能否把拒绝当数据"],
];

export default function Landing() {
  useEffect(() => track("landing_view"), []);
  return (
    <div>
      <header className="bg-gradient-to-br from-navy via-[#0c2340] to-[#142b52] text-white">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <div className="text-xs font-semibold tracking-[0.35em] text-brand-orange">
            CAREER PACER · RUN WITH YOU
          </div>
          <h1 className="mt-4 text-4xl font-bold tracking-wide">求职陪跑</h1>
          <p className="mt-2 text-lg text-[#b9c6e8]">
            投了很多没回音？做一次 AI 诊断，梳理可能的卡点，确定一个本周就能做的验证动作。
          </p>
          <div className="my-5 h-1 w-16 bg-brand-orange" />
          <p className="max-w-2xl text-sm leading-7 text-[#cfd9f2]">
            与 AI 诊断师完成一场结构化对话（快速档约 20 分钟），自动生成一份咨询级《求职准备度诊断报告》——
            七个维度、0–7 分，<b className="text-white">每一分都有你自己的原话做证据</b>。
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <Link
              to="/auth"
              className="rounded-lg bg-brand-orange px-6 py-3 font-bold text-white shadow-lg transition hover:brightness-110"
            >
              开始我的诊断 →
            </Link>
            <span className="text-xs text-[#8da2d0]">AI 诊断师 · 全程免费 · 支持化名完成</span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-12">
        <h2 className="text-xl font-bold text-navy">七个维度，把求职拆成七件可评分的任务</h2>
        <p className="mt-1 text-sm text-gray-500">
          分数低是进度低，不是能力低——低分不是警报，而是地图。
        </p>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {DIMS.map(([no, name, desc]) => (
            <div key={no} className="rounded-xl border border-line border-t-4 border-t-brand-blue p-4">
              <div className="text-[11px] font-bold tracking-[0.2em] text-brand-orange">
                {no} · DIMENSION
              </div>
              <div className="mt-1 font-bold text-navy">{name}</div>
              <div className="mt-1 text-sm text-gray-500">{desc}</div>
            </div>
          ))}
        </div>

        <div className="mt-12 rounded-2xl bg-navy p-8 text-white">
          <div className="text-sm font-bold text-brand-orange">报告长什么样？</div>
          <p className="mt-2 text-sm leading-7 text-[#cfd9f2]">
            9 章结构：速读版 → 快照 → 评分方法 → 评分总览（雷达图）→ 七维逐项详解（引你的原话作证据）→
            亮点与潜力 → 结构性结论 → 行动计划（本周 3 个动作，每个附直接可用的交付物模板）→ 结语。
            报告中的每句引用都经过程序与对话原文逐字核验。
          </p>
          <p className="mt-4 text-xs text-[#8da2d0]">
            测试版提示：报告生成后请及时下载保存。本产品输出由 AI 生成，为单次对话观察的参考意见。
          </p>
        </div>

        <div className="mt-12 text-center">
          <Link
            to="/auth"
            className="inline-block rounded-lg bg-brand-blue px-8 py-3 font-bold text-white transition hover:brightness-110"
          >
            免费开始诊断
          </Link>
        </div>
      </main>

      <footer className="border-t border-line py-8 text-center text-xs tracking-widest text-gray-400">
        求职陪跑 · CAREER PACER — RUN WITH YOU · AI 生成内容显式标识
      </footer>
    </div>
  );
}
