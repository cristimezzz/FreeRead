// 3D 链接云图的 React 外壳：布局（layout.ts）在这里算好并缓存，绘制交给 KgScene（three.js，懒加载）。
// 同一个组件既用在侧栏，也用在展开后铺满阅读区的覆盖层里（KgPanel 用 portal 放进去）。

import { useEffect, useMemo, useRef, useState } from "react";
import { exitMs } from "../../components/motion";
import { PanelNote } from "../../components/SidePanel";
import { computeLayout } from "./layout";
import type { KgScene, Selection } from "./KgScene";
import type { CloudLink, CloudNode } from "./useKg";

export type { Selection };

interface Props {
  /** 全图（布局用，筛选类型时位置不变） */
  all: { nodes: CloudNode[]; links: CloudLink[] };
  /** 当前显示的部分 */
  nodes: CloudNode[];
  links: CloudLink[];
  selected: Selection;
  onSelect: (s: Selection) => void;
}

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function KgCloud({ all, nodes, links, selected, onSelect }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<KgScene | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const positions = useMemo(() => computeLayout(all.nodes, all.links), [all]);

  // 创建场景（只一次）
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    if (!webglAvailable()) {
      setError("这台设备不支持 WebGL，无法显示 3D 图谱。");
      return;
    }
    let disposed = false;
    let ro: ResizeObserver | null = null;
    let themeObs: MutationObserver | null = null;
    void import("./KgScene")
      .then(({ KgScene }) => {
        if (disposed) return;
        const scene = new KgScene(el, {
          onSelect: (s) => onSelectRef.current(s),
          reducedMotion: exitMs() === 0,
        });
        sceneRef.current = scene;
        ro = new ResizeObserver(() => scene.resize());
        ro.observe(el);
        // 换主题（data-theme / 令牌变化）时重新上色
        themeObs = new MutationObserver(() => scene.setTheme());
        themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "style"] });
        setReady(true);
      })
      .catch((e) => setError(`加载 3D 图谱失败：${e instanceof Error ? e.message : e}`));
    return () => {
      disposed = true;
      ro?.disconnect();
      themeObs?.disconnect();
      sceneRef.current?.dispose();
      sceneRef.current = null;
    };
  }, []);

  // 数据（筛选类型时只换显示的部分，布局不变）；第一次有数据时对准全貌
  const fitted = useRef(false);
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !ready) return;
    scene.setData(nodes, links, positions);
    scene.setSelected(selected);
    if (!fitted.current && nodes.length) {
      fitted.current = true;
      scene.fit(false);
    }
    // 选中状态在数据换掉后重放一次；selected 自身的变化由下一个 effect 处理
  }, [nodes, links, positions, ready]);

  useEffect(() => {
    if (ready) sceneRef.current?.setSelected(selected);
  }, [selected, ready]);

  return (
    <div className="kg-cloud" role="group" aria-label={`知识图谱云图：${nodes.length} 个实体、${links.length} 条关系`}>
      <div className="kg-cloud-canvas" ref={box} />
      {error && (
        <PanelNote error className="kg-cloud-note m-0">
          {error}
        </PanelNote>
      )}
      {!ready && !error && <PanelNote className="kg-cloud-note m-0">正在加载 3D 图谱…</PanelNote>}
    </div>
  );
}
