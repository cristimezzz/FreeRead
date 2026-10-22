import { useEffect, useState } from "react";
import { isTauri } from "../../api/core";
import { useApp } from "../../app/store";
import { Button, Progress, Spinner } from "../../components/ui";
import {
  appVersion,
  applyUpdate,
  avatarSrc,
  checkUpdate,
  type Contributor,
  downloadUpdate,
  formatDate,
  formatSize,
  listContributors,
  openExternal,
  plainNotes,
  REPO_URL,
  type UpdateInfo,
} from "./about";
import { Icon } from "../../components/icons";
import { Group, Row } from "./Row";

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
        <Button small variant="ghost" icon="external" onClick={() => void openExternal(REPO_URL)}>
          GitHub
        </Button>
      </Row>

      <Row title="检查更新" desc={updateDesc(step, desktop)}>
        {desktop && <UpdateActions step={step} onCheck={check} onDownload={download} onApply={apply} />}
      </Row>
      {step.s === "downloading" && <Progress value={step.progress} className="about-bar" />}
      {info?.available && info.notes.trim() && (
        <details className="about-more">
          <summary>
            <Icon name="chevronRight" size={16} />
            {info.latest} 更新说明
          </summary>
          <div className="about-notes">{plainNotes(info.notes)}</div>
        </details>
      )}

      <h3 className="about-h">贡献者</h3>
      {!desktop ? (
        <p className="set-hint">贡献者列表在桌面版里从 GitHub 获取。</p>
      ) : peopleErr ? (
        <p className="set-hint">无法获取贡献者列表：{peopleErr}</p>
      ) : !people ? (
        <p className="set-hint about-loading">
          <Spinner size={14} />
          正在从 GitHub 获取…
        </p>
      ) : (
        <ul className="contributors">
          {people.map((p) => (
            <li key={p.login}>
              <button type="button" className="contributor" onClick={() => void openExternal(p.htmlUrl)}>
                <img src={avatarSrc(p.avatarUrl, 36)} alt="" width={36} height={36} loading="lazy" />
                <span>
                  <b>{p.login}</b>
                  <span>{p.contributions} 次提交</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="set-hint">
        欢迎提交问题和改进。
        <Button variant="ghost" small onClick={() => void openExternal(`${REPO_URL}/graphs/contributors`)}>
          在 GitHub 上查看全部
        </Button>
      </p>
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
      return step.info.portable
        ? `已保存到 ${step.path}，退出 FreeRead 后解压覆盖原目录即可`
        : "下载完成，已通过校验。安装时 FreeRead 会关闭，装好后自动重新打开";
    case "checked": {
      const { info } = step;
      if (!info.available) return `已是最新版本（${info.current}）`;
      const date = formatDate(info.publishedAt);
      const size = info.asset ? `，${info.portable ? "便携版" : "安装包"} ${formatSize(info.asset.size)}` : "";
      return `发现新版本 ${info.latest}${date && `（${date} 发布）`}${size}`;
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
      <Button small variant="primary" onClick={() => onDownload(info)}>
        下载更新
      </Button>
    ) : (
      <Button small icon="external" onClick={() => void openExternal(info.releaseUrl)}>
        前往下载页
      </Button>
    );
  }
  if (step.s === "downloading") return <Button small disabled>下载中…</Button>;
  if (step.s === "downloaded") {
    return (
      <Button small variant="primary" onClick={onApply}>
        {step.info.portable ? "在文件夹中显示" : "安装并重启"}
      </Button>
    );
  }
  return (
    <Button small disabled={step.s === "checking"} onClick={onCheck}>
      {step.s === "checked" ? "重新检查" : "检查更新"}
    </Button>
  );
}
