import { useEffect, useState } from "react";
import { isTauri } from "../../api/core";
import { useApp } from "../../app/store";
import { ProgressBar, Spinner } from "../../components/controls";
import { Icon } from "../../components/icons";
import { Button } from "../../components/ui/button";
import {
  appVersion,
  ASSET_LABEL,
  applyUpdate,
  avatarSrc,
  checkUpdate,
  type Contributor,
  downloadUpdate,
  downloadedHint,
  formatDate,
  formatSize,
  listContributors,
  openExternal,
  plainNotes,
  REPO_URL,
  type UpdateInfo,
} from "./about";
import { Group, Hint, More, Row } from "./Row";

type UpdateStep =
  | { s: "idle" }
  | { s: "checking" }
  | { s: "checked"; info: UpdateInfo }
  | { s: "downloading"; info: UpdateInfo; progress: number }
  | { s: "downloaded"; info: UpdateInfo; path: string };

export function AboutSection({ title }: { title: string }) {
  const toast = useApp((s) => s.toast);
  const [version, setVersion] = useState<string | null>(null);
  const [step, setStep] = useState<UpdateStep>({ s: "idle" });
  const [people, setPeople] = useState<Contributor[] | null>(null);
  const [peopleErr, setPeopleErr] = useState<string | null>(null);
  const desktop = isTauri();

  useEffect(() => {
    void appVersion().then(setVersion);
    if (!desktop) return;
    let live = true;
    listContributors()
      .then((list) => live && setPeople(list))
      .catch((e) => live && setPeopleErr(String(e)));
    return () => {
      live = false;
    };
  }, [desktop]);

  const check = async () => {
    setStep({ s: "checking" });
    try {
      setStep({ s: "checked", info: await checkUpdate() });
    } catch (e) {
      setStep({ s: "idle" });
      toast(`检查更新失败：${e}`);
    }
  };

  const download = async (info: UpdateInfo) => {
    setStep({ s: "downloading", info, progress: 0 });
    try {
      const path = await downloadUpdate((progress) => setStep({ s: "downloading", info, progress }));
      setStep({ s: "downloaded", info, path });
    } catch (e) {
      setStep({ s: "checked", info });
      toast(`${e}`);
    }
  };

  const apply = async () => {
    try {
      await applyUpdate();
    } catch (e) {
      toast(`${e}`);
    }
  };

  const info = step.s === "idle" || step.s === "checking" ? null : step.info;

  return (
    <Group id="about" title={title}>
      <Row
        title={`FreeRead ${version ?? "开发版"}`}
        desc="开源的论文阅读与翻译工具，按 AGPL-3.0 协议发布"
      >
        <Button variant="ghost" size="sm" onClick={() => void openExternal(REPO_URL)}>
          <Icon name="external" />
          GitHub
        </Button>
      </Row>

      <Row title="检查更新" desc={updateDesc(step, desktop)}>
        {desktop && <UpdateActions step={step} onCheck={check} onDownload={download} onApply={apply} />}
      </Row>
      {step.s === "downloading" && <ProgressBar value={step.progress} className="-mt-1.5 mb-2" />}
      {info?.available && info.notes.trim() && (
        <More label={`${info.latest} 更新说明`}>
          <div className="text-foreground/80 mt-1.5 mb-1 max-h-[16em] overflow-auto rounded-md border px-3.5 py-3 text-[12.5px] leading-relaxed wrap-anywhere whitespace-pre-wrap">
            {plainNotes(info.notes)}
          </div>
        </More>
      )}

      <h3 className="mt-5.5 mb-1 text-sm font-medium">贡献者</h3>
      {!desktop ? (
        <Hint>贡献者列表在桌面版里从 GitHub 获取。</Hint>
      ) : peopleErr ? (
        <Hint>无法获取贡献者列表：{peopleErr}</Hint>
      ) : !people ? (
        <Hint className="flex items-center gap-2">
          <Spinner size={14} />
          正在从 GitHub 获取…
        </Hint>
      ) : (
        <ul className="mt-2.5 grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-2">
          {people.map((p) => (
            <li key={p.login}>
              <button
                type="button"
                className="bg-card hover:border-muted-foreground focus-visible:outline-ring flex w-full cursor-pointer items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2"
                onClick={() => void openExternal(p.htmlUrl)}
              >
                <img
                  className="bg-muted flex-none rounded-full"
                  src={avatarSrc(p.avatarUrl, 36)}
                  alt=""
                  width={36}
                  height={36}
                  loading="lazy"
                />
                <span className="min-w-0">
                  <b className="block truncate text-[13.5px] font-medium">{p.login}</b>
                  <span className="text-muted-foreground block truncate text-xs">{p.contributions} 次提交</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <Hint>
        欢迎提交问题和改进。
        <Button variant="ghost" size="sm" onClick={() => void openExternal(`${REPO_URL}/graphs/contributors`)}>
          在 GitHub 上查看全部
        </Button>
      </Hint>
    </Group>
  );
}

function updateDesc(step: UpdateStep, desktop: boolean): string {
  if (!desktop) return "检查更新只在桌面版里可用";
  switch (step.s) {
    case "idle":
      return "从 GitHub Release 获取最新版本，只在点按钮时联网";
    case "checking":
      return "正在检查…";
    case "downloading":
      return `正在下载 ${step.info.asset?.name ?? ""}（${Math.round(step.progress * 100)}%）`;
    case "downloaded":
      return downloadedHint(step.info.kind, step.path);
    case "checked": {
      const { info } = step;
      if (!info.available) return `已是最新版本（${info.current}）`;
      const date = formatDate(info.publishedAt);
      const size = info.asset ? `，${ASSET_LABEL[info.kind]} ${formatSize(info.asset.size)}` : "";
      const aur = info.kind === "aur" ? "，用 AUR 助手（如 yay -Syu）更新" : "";
      return `发现新版本 ${info.latest}${date && `（${date} 发布）`}${size}${aur}`;
    }
  }
}

function UpdateActions({
  step,
  onCheck,
  onDownload,
  onApply,
}: {
  step: UpdateStep;
  onCheck: () => void;
  onDownload: (info: UpdateInfo) => void;
  onApply: () => void;
}) {
  if (step.s === "checked" && step.info.available) {
    const { info } = step;
    return info.asset ? (
      <Button size="sm" onClick={() => onDownload(info)}>
        下载更新
      </Button>
    ) : (
      <Button variant="outline" size="sm" onClick={() => void openExternal(info.releaseUrl)}>
        <Icon name="external" />
        前往下载页
      </Button>
    );
  }
  if (step.s === "downloading") {
    return (
      <Button variant="outline" size="sm" disabled>
        下载中…
      </Button>
    );
  }
  if (step.s === "downloaded") {
    return (
      <Button size="sm" onClick={onApply}>
        {step.info.kind === "nsis" ? "安装并重启" : "在文件夹中显示"}
      </Button>
    );
  }
  return (
    <Button variant="outline" size="sm" disabled={step.s === "checking"} onClick={onCheck}>
      {step.s === "checked" ? "重新检查" : "检查更新"}
    </Button>
  );
}
