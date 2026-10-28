// AI Elements 的 Shimmer（流式 / 等待中的文字微光）。原版靠 motion 做动画，这里改成 CSS 关键帧（styles/index.css 的 shimmer-sweep），
// 接口不变，少一个依赖。prefers-reduced-motion 时动画归零（index.css 末尾统一处理）。

import type { CSSProperties, ElementType } from "react";
import { memo } from "react";
import { cn } from "@/lib/utils";

export interface TextShimmerProps {
  children: string;
  as?: ElementType;
  className?: string;
  /** 扫过一轮的秒数 */
  duration?: number;
  /** 高光宽度系数：每个字符多少 px */
  spread?: number;
}

const ShimmerComponent = ({ children, as: Component = "span", className, duration = 2, spread = 2 }: TextShimmerProps) => (
  <Component
    className={cn(
      "relative inline-block bg-[length:250%_100%,auto] bg-clip-text text-transparent",
      "[--bg:linear-gradient(90deg,#0000_calc(50%-var(--spread)),var(--background),#0000_calc(50%+var(--spread)))] [background-repeat:no-repeat,padding-box]",
      "animate-[shimmer-sweep_var(--shimmer-duration)_linear_infinite]",
      className,
    )}
    style={
      {
        "--spread": `${(children?.length ?? 0) * spread}px`,
        "--shimmer-duration": `${duration}s`,
        backgroundImage: "var(--bg), linear-gradient(var(--muted-foreground), var(--muted-foreground))",
      } as CSSProperties
    }
  >
    {children}
  </Component>
);

export const Shimmer = memo(ShimmerComponent);
