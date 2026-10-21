// 图谱 3D 场景（three.js，命令式）。KgCloud 打开图谱时才 import() 这个模块，three 打成单独的 chunk。
//
// - 节点：球体（颜色 = 类型令牌 --kg-*，大小 = 重要性）+ DOM 文字标签（CSS2D，固定像素字号，远近都清楚）；
// - 关系：按像素宽度画的线（Line2），线型区分关系类别，目标端有箭头；中点是可点击的关系名标签；
// - 悬停 / 选中一个节点时只突出它和一跳邻居，并标出它的全部关系名；
// - 按需渲染：只在镜头移动、补间、悬停变化时画一帧。

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { LINE_STYLE, boundingSphere, edgeLabelSet, labelBudget, nodeRadius, type Vec3 } from "./layout";
import { typeLabel, type CloudLink, type CloudNode } from "./useKg";

export type Selection = { kind: "node" | "link"; id: string } | null;

interface Options {
  onSelect: (s: Selection) => void;
  reducedMotion: boolean;
}

interface NodeObj {
  node: CloudNode;
  pos: THREE.Vector3;
  r: number;
  mesh: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>;
  label: CSS2DObject;
}

interface LinkObj {
  link: CloudLink;
  line: Line2;
  arrow: THREE.Mesh<THREE.ConeGeometry, THREE.MeshBasicMaterial>;
  label: CSS2DObject;
}

const LINE_W = 1.5;
const LINE_W_LIT = 3;
const ARROW_LEN = 7;
const FOV = 45;

function token(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

export class KgScene {
  private renderer: THREE.WebGLRenderer;
  private labels: CSS2DRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(FOV, 1, 1, 8000);
  private controls: OrbitControls;
  private raycaster = new THREE.Raycaster();
  private sphere = new THREE.SphereGeometry(1, 28, 20);
  private cone = new THREE.ConeGeometry(2.4, ARROW_LEN, 14);
  private group = new THREE.Group();
  private nodes = new Map<string, NodeObj>();
  private links: LinkObj[] = [];
  private named = new Set<string>();
  private budget = { nodes: 20, edges: 25 }; // 平时显示名字的节点数 / 关系数，随画布大小变
  private hover: string | null = null;
  private selected: Selection = null;
  private frame = 0;
  private tween: { from: [THREE.Vector3, THREE.Vector3]; to: [THREE.Vector3, THREE.Vector3]; t0: number; ms: number } | null =
    null;
  private down: { x: number; y: number } | null = null;
  private width = 1;
  private height = 1;
  private colors = { line: "#65645E", accent: "#D97757" };

  constructor(
    private container: HTMLElement,
    private opts: Options,
  ) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.domElement.className = "kg3-canvas";
    container.appendChild(this.renderer.domElement);

    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "kg3-overlay";
    container.appendChild(this.labels.domElement);

    this.scene.add(this.group);
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(0.4, 0.8, 1);
    this.camera.add(sun); // 光随镜头走，转到哪一面都有高光
    this.scene.add(this.camera);
    this.camera.position.set(0, 0, 400);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = !opts.reducedMotion;
    this.controls.dampingFactor = 0.12;
    this.controls.rotateSpeed = 0.7;
    this.controls.addEventListener("change", () => this.requestRender());

    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", this.onDown);
    el.addEventListener("pointerup", this.onUp);
    el.addEventListener("pointermove", this.onMove);
    el.addEventListener("pointerleave", this.onLeave);

    this.readColors();
    this.resize();
  }

  // ------------------------------------------------------------ 数据

  /** positions 是全图布局（筛掉的类型也在里面），nodes / links 是当前要显示的部分。 */
  setData(nodes: CloudNode[], links: CloudLink[], positions: Map<string, Vec3>): void {
    this.clear();
    for (const node of nodes) {
      const p = positions.get(node.id) ?? { x: 0, y: 0, z: 0 };
      const r = nodeRadius(node.val);
      const mesh = new THREE.Mesh(
        this.sphere,
        new THREE.MeshStandardMaterial({ roughness: 0.5, metalness: 0.05, transparent: true }),
      );
      mesh.scale.setScalar(r);
      mesh.position.set(p.x, p.y, p.z);
      mesh.userData.id = node.id;
      const div = document.createElement("div");
      div.className = "kg3-label";
      const dot = document.createElement("span");
      dot.className = "kg3-dot";
      dot.style.background = `var(--kg-${node.type.toLowerCase()})`;
      const text = document.createElement("span");
      text.textContent = node.name.length > 32 ? `${node.name.slice(0, 31)}…` : node.name;
      div.append(dot, text);
      div.title = `${typeLabel(node.type)}：${node.name}`;
      const label = new CSS2DObject(div);
      label.center.set(0.5, 0); // 标签上沿对齐球的下方
      label.position.set(0, -1.15, 0); // 在 mesh 的局部坐标里（已按半径缩放）
      mesh.add(label);
      this.group.add(mesh);
      this.nodes.set(node.id, { node, pos: mesh.position.clone(), r, mesh, label });
    }

    const pairCount = new Map<string, number>();
    for (const link of links) {
      const a = this.nodes.get(link.source);
      const b = this.nodes.get(link.target);
      if (!a || !b) continue;
      const dir = b.pos.clone().sub(a.pos);
      const len = dir.length() || 1;
      dir.divideScalar(len);
      const start = a.pos.clone().addScaledVector(dir, a.r + 1);
      const tip = b.pos.clone().addScaledVector(dir, -(b.r + 1));
      const end = tip.clone().addScaledVector(dir, -ARROW_LEN * 0.8);

      const style = LINE_STYLE[link.type] ?? "solid";
      const geo = new LineGeometry();
      geo.setPositions([start.x, start.y, start.z, end.x, end.y, end.z]);
      const mat = new LineMaterial({
        linewidth: LINE_W,
        transparent: true,
        dashed: style !== "solid",
        dashSize: style === "dotted" ? 1.5 : 6,
        gapSize: style === "dotted" ? 3 : 4,
        worldUnits: false,
      });
      mat.resolution.set(this.width, this.height);
      const line = new Line2(geo, mat);
      line.computeLineDistances();
      this.group.add(line);

      const arrow = new THREE.Mesh(this.cone, new THREE.MeshBasicMaterial({ transparent: true }));
      arrow.position.copy(tip).addScaledVector(dir, -ARROW_LEN / 2);
      arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
      this.group.add(arrow);

      // 同一对实体之间的多条关系：标签上下错开
      const key = [link.source, link.target].sort().join("|");
      const k = pairCount.get(key) ?? 0;
      pairCount.set(key, k + 1);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "kg3-edge";
      btn.textContent = link.label;
      btn.style.marginTop = `${k * 22}px`;
      btn.setAttribute("aria-label", `关系：${a.node.name} ${link.label} ${b.node.name}`);
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this.opts.onSelect({ kind: "link", id: link.id });
      });
      // 从节点移到它的关系名上时保持悬停，否则标签会在点到之前消失
      btn.addEventListener("pointerenter", () => {
        if (btn.classList.contains("is-lit")) this.cancelUnhover();
      });
      btn.addEventListener("pointerleave", () => this.unhoverSoon());
      const label = new CSS2DObject(btn);
      label.position.copy(a.pos).add(b.pos).multiplyScalar(0.5);
      this.group.add(label);
      this.links.push({ link, line, arrow, label });
    }
    this.readColors();
    this.pickNamed();
    this.applyState();
  }

  private pickNamed(): void {
    this.named = new Set(
      [...this.nodes.values()]
        .map((n) => n.node)
        .sort((a, b) => b.val - a.val)
        .slice(0, this.budget.nodes)
        .map((n) => n.id),
    );
  }

  setSelected(sel: Selection): void {
    const prev = this.selected;
    this.selected = sel;
    this.applyState();
    if (sel?.kind === "node") {
      const ids = new Set([sel.id]);
      for (const l of this.links)
        if (l.link.source === sel.id || l.link.target === sel.id) ids.add(l.link.source).add(l.link.target);
      this.frameIds(ids, 1.25);
    } else if (sel?.kind === "link") {
      const l = this.links.find((x) => x.link.id === sel.id);
      if (l) this.frameIds(new Set([l.link.source, l.link.target]), 2.2);
    } else if (prev) {
      this.fit();
    }
  }

  /** 镜头对准全部节点。 */
  fit(animate = true): void {
    this.frameIds(new Set(this.nodes.keys()), 1, animate, 0.9);
  }

  /** 主题变化（--kg-*、--ink3、--accent）后重新上色。 */
  setTheme(): void {
    this.readColors();
    this.applyState();
  }

  resize(): void {
    this.width = Math.max(1, this.container.clientWidth);
    this.height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(this.width, this.height);
    this.labels.setSize(this.width, this.height);
    this.camera.aspect = this.width / this.height;
    this.camera.updateProjectionMatrix();
    for (const l of this.links) l.line.material.resolution.set(this.width, this.height);
    const budget = labelBudget(this.width, this.height);
    if (budget.nodes !== this.budget.nodes || budget.edges !== this.budget.edges) {
      this.budget = budget;
      this.pickNamed();
      this.applyState();
    }
    this.requestRender();
  }

  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.cancelUnhover();
    const el = this.renderer.domElement;
    el.removeEventListener("pointerdown", this.onDown);
    el.removeEventListener("pointerup", this.onUp);
    el.removeEventListener("pointermove", this.onMove);
    el.removeEventListener("pointerleave", this.onLeave);
    this.controls.dispose();
    this.clear();
    this.sphere.dispose();
    this.cone.dispose();
    this.renderer.dispose();
    el.remove();
    this.labels.domElement.remove();
  }

  // ------------------------------------------------------------ 状态 → 外观

  private readColors(): void {
    this.colors = { line: token("--ink3", "#65645E"), accent: token("--accent", "#D97757") };
    for (const n of this.nodes.values())
      n.mesh.material.color.set(token(`--kg-${n.node.type.toLowerCase()}`, this.colors.line));
  }

  /** 焦点：悬停优先于选中；返回要突出的节点和连线（null 表示不突出任何东西，全部正常显示）。 */
  private focus(): { nodes: Set<string>; links: Set<string>; nodeId: string | null } | null {
    const nodeId = this.hover ?? (this.selected?.kind === "node" ? this.selected.id : null);
    if (nodeId) {
      const nodes = new Set([nodeId]);
      const links = new Set<string>();
      for (const l of this.links)
        if (l.link.source === nodeId || l.link.target === nodeId) {
          nodes.add(l.link.source).add(l.link.target);
          links.add(l.link.id);
        }
      return { nodes, links, nodeId };
    }
    if (this.selected?.kind === "link") {
      const l = this.links.find((x) => x.link.id === this.selected?.id);
      if (l) return { nodes: new Set([l.link.source, l.link.target]), links: new Set([l.link.id]), nodeId: null };
    }
    return null;
  }

  private applyState(): void {
    const f = this.focus();
    const shownEdges = f
      ? f.nodeId
        ? edgeLabelSet(
            [...this.nodes.values()].map((n) => n.node),
            this.links.map((l) => l.link),
            f.nodeId,
          )
        : f.links
      : edgeLabelSet(
          [...this.nodes.values()].map((n) => n.node),
          this.links.map((l) => l.link),
          null,
          this.budget.edges,
        );
    for (const n of this.nodes.values()) {
      const lit = !f || f.nodes.has(n.node.id);
      n.mesh.material.opacity = lit ? 1 : 0.16;
      n.mesh.material.depthWrite = lit;
      const show = f ? f.nodes.has(n.node.id) : this.named.has(n.node.id);
      n.label.visible = show;
      // 焦点节点；选中关系时是它的两端
      n.label.element.classList.toggle("is-focus", !!f && (f.nodeId ? n.node.id === f.nodeId : f.nodes.has(n.node.id)));
      n.label.element.classList.toggle("is-selected", this.selected?.kind === "node" && this.selected.id === n.node.id);
    }
    for (const l of this.links) {
      const lit = !!f && f.links.has(l.link.id);
      const dim = !!f && !lit;
      const color = lit ? this.colors.accent : this.colors.line;
      l.line.material.color.set(color);
      l.line.material.linewidth = lit ? LINE_W_LIT : LINE_W;
      l.line.material.opacity = dim ? 0.08 : l.link.stale ? 0.35 : lit ? 1 : 0.6;
      l.arrow.material.color.set(color);
      l.arrow.material.opacity = dim ? 0.08 : lit ? 1 : 0.7;
      l.label.visible = shownEdges.has(l.link.id);
      l.label.element.classList.toggle("is-lit", lit);
      l.label.element.classList.toggle(
        "is-selected",
        this.selected?.kind === "link" && this.selected.id === l.link.id,
      );
      l.label.element.classList.toggle("is-stale", l.link.stale);
    }
    this.requestRender();
  }

  private clear(): void {
    for (const n of this.nodes.values()) {
      n.mesh.material.dispose();
      n.label.element.remove();
    }
    for (const l of this.links) {
      l.line.geometry.dispose();
      l.line.material.dispose();
      l.arrow.material.dispose();
      l.label.element.remove();
    }
    this.group.clear();
    this.nodes.clear();
    this.links = [];
  }

  // ------------------------------------------------------------ 镜头

  private frameIds(ids: Set<string>, margin: number, animate = true, coverage = 1): void {
    const pts = [...ids].map((id) => this.nodes.get(id)?.pos).filter((p): p is THREE.Vector3 => !!p);
    if (!pts.length) return;
    const { center, radius } = boundingSphere(pts, coverage);
    const target = new THREE.Vector3(center.x, center.y, center.z);
    const vfov = THREE.MathUtils.degToRad(this.camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * this.camera.aspect);
    const dist = ((radius + 16) / Math.tan(Math.min(vfov, hfov) / 2)) * margin;
    const dir = this.camera.position.clone().sub(this.controls.target);
    if (dir.lengthSq() < 1e-6) dir.set(0, 0, 1);
    const pos = target.clone().addScaledVector(dir.normalize(), dist);
    const ms = animate && !this.opts.reducedMotion ? 650 : 0;
    if (!ms) {
      this.tween = null;
      this.camera.position.copy(pos);
      this.controls.target.copy(target);
      this.controls.update();
      this.requestRender();
      return;
    }
    this.tween = {
      from: [this.camera.position.clone(), this.controls.target.clone()],
      to: [pos, target],
      t0: performance.now(),
      ms,
    };
    this.requestRender();
  }

  // ------------------------------------------------------------ 渲染

  private requestRender = (): void => {
    if (!this.frame) this.frame = requestAnimationFrame(this.renderFrame);
  };

  private renderFrame = (): void => {
    this.frame = 0;
    let again = false;
    if (this.tween) {
      const t = Math.min(1, (performance.now() - this.tween.t0) / this.tween.ms);
      const k = ease(t);
      this.camera.position.lerpVectors(this.tween.from[0], this.tween.to[0], k);
      this.controls.target.lerpVectors(this.tween.from[1], this.tween.to[1], k);
      if (t < 1) again = true;
      else this.tween = null;
    }
    // 阻尼还在衰减时 update() 会触发 change → requestRender，这里不用再排
    this.controls.update();
    this.fadeLabels();
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
    this.declutter();
    if (again) this.requestRender();
  };

  /**
   * 文字标签去重叠：按优先级（焦点 / 选中 → 突出的关系 → 最重要的 6 个节点名 → 重要关系名 → 其余节点名）依次摆放，
   * 和已摆放的标签重叠的先藏起来（visibility，不影响 CSS2D 控制的 display），转动镜头后重新判断。
   */
  private declutter(): void {
    type Item = { el: HTMLElement; rank: number };
    const items: Item[] = [];
    const named = [...this.nodes.values()].filter((n) => n.label.visible).sort((a, b) => b.node.val - a.node.val);
    named.forEach((n, i) => {
      const el = n.label.element;
      const top = el.classList.contains("is-focus") || el.classList.contains("is-selected");
      // 关系名排在大部分节点名前面：侧栏里地方小，优先保住"谁和谁是什么关系"
      items.push({ el, rank: top ? 0 : i < 6 ? 2 : 4 });
    });
    for (const l of this.links) {
      if (!l.label.visible) continue;
      const el = l.label.element;
      const rank = el.classList.contains("is-selected") ? 0 : el.classList.contains("is-lit") ? 1 : 3;
      items.push({ el, rank });
    }
    items.sort((a, b) => a.rank - b.rank);
    for (const it of items) it.el.style.visibility = "";
    const placed: DOMRect[] = [];
    for (const it of items) {
      const r = it.el.getBoundingClientRect();
      const hit = placed.some((p) => r.left < p.right && r.right > p.left && r.top < p.bottom && r.bottom > p.top);
      if (hit && it.rank > 0) it.el.style.visibility = "hidden";
      else placed.push(r);
    }
  }

  /** 离镜头越远的节点名越淡（近处 1，远处 0.4），前后层次更清楚；焦点节点不变淡。 */
  private fadeLabels(): void {
    const cam = this.camera.position;
    const ds = [...this.nodes.values()].filter((n) => n.label.visible).map((n) => n.pos.distanceTo(cam));
    if (!ds.length) return;
    const near = Math.min(...ds);
    const far = Math.max(...ds);
    for (const n of this.nodes.values()) {
      if (!n.label.visible) continue;
      const t = far > near ? (n.pos.distanceTo(cam) - near) / (far - near) : 0;
      const focus = n.label.element.classList.contains("is-focus");
      n.label.element.style.opacity = focus ? "1" : String(1 - 0.6 * t);
    }
  }

  // ------------------------------------------------------------ 指针

  private pick(e: PointerEvent): string | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(ndc, this.camera);
    const hits = this.raycaster.intersectObjects(
      [...this.nodes.values()].map((n) => n.mesh),
      false,
    );
    return (hits[0]?.object.userData.id as string | undefined) ?? null;
  }

  private setHover(id: string | null): void {
    if (id === this.hover) return;
    this.hover = id;
    this.renderer.domElement.style.cursor = id ? "pointer" : "";
    this.applyState();
  }

  private onDown = (e: PointerEvent): void => {
    this.down = { x: e.clientX, y: e.clientY };
  };

  private onUp = (e: PointerEvent): void => {
    const d = this.down;
    this.down = null;
    if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) return; // 拖动旋转，不是点击
    const id = this.pick(e);
    this.opts.onSelect(id ? { kind: "node", id } : null);
  };

  private unhoverTimer = 0;
  private static UNHOVER_MS = 350;

  /** 离开节点后稍等再取消悬停：给指针留时间移到这个节点的关系名上。 */
  private unhoverSoon(): void {
    if (!this.hover || this.unhoverTimer) return;
    this.unhoverTimer = window.setTimeout(() => {
      this.unhoverTimer = 0;
      this.setHover(null);
    }, KgScene.UNHOVER_MS);
  }

  private cancelUnhover(): void {
    clearTimeout(this.unhoverTimer);
    this.unhoverTimer = 0;
  }

  private onMove = (e: PointerEvent): void => {
    if (e.buttons) return; // 拖动中不改悬停
    const id = this.pick(e);
    if (id) {
      this.cancelUnhover();
      this.setHover(id);
    } else this.unhoverSoon();
  };

  private onLeave = (): void => this.unhoverSoon();
}
