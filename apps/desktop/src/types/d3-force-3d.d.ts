// d3-force-3d 没有自带类型；只声明图谱布局（features/kg/layout.ts）用到的部分。

declare module "d3-force-3d" {
  export interface SimNode {
    id: string;
    index?: number;
    x?: number;
    y?: number;
    z?: number;
    vx?: number;
    vy?: number;
    vz?: number;
    fx?: number | null;
    fy?: number | null;
    fz?: number | null;
  }

  export interface SimLink<N extends SimNode> {
    source: string | N;
    target: string | N;
  }

  export interface Force {
    (alpha: number): void;
  }

  export interface Simulation<N extends SimNode> {
    force(name: string, force: Force | null): this;
    tick(iterations?: number): this;
    stop(): this;
    nodes(): N[];
    alphaDecay(decay: number): this;
  }

  export interface LinkForce<N extends SimNode, L extends SimLink<N>> extends Force {
    id(fn: (node: N) => string): this;
    distance(d: number | ((link: L) => number)): this;
    strength(s: number | ((link: L) => number)): this;
  }

  export interface ManyBodyForce extends Force {
    strength(s: number): this;
    distanceMax(d: number): this;
  }

  export interface CollideForce<N extends SimNode> extends Force {
    radius(r: number | ((node: N) => number)): this;
  }

  export function forceSimulation<N extends SimNode>(nodes: N[], numDimensions?: 1 | 2 | 3): Simulation<N>;
  export function forceLink<N extends SimNode, L extends SimLink<N>>(links: L[]): LinkForce<N, L>;
  export function forceManyBody(): ManyBodyForce;
  export interface PositionForce extends Force {
    strength(s: number): this;
  }

  export function forceX(x?: number): PositionForce;
  export function forceY(y?: number): PositionForce;
  export function forceZ(z?: number): PositionForce;
  export function forceCenter(x?: number, y?: number, z?: number): Force;
  export function forceCollide<N extends SimNode>(radius?: number | ((node: N) => number)): CollideForce<N>;
}
