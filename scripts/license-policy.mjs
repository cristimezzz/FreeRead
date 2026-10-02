const allowed = /^(AGPL-3\.0(?:-only|-or-later)?|GPL-3\.0(?:-only|-or-later)?|LGPL-\d\.\d(?:-only|-or-later)?|MIT(?:-0)?|Apache-2\.0|BSD-[234]-Clause|ISC|MPL-2\.0|CC0-1\.0|Unlicense|OFL-1\.1|0BSD|CC-BY-4\.0|Python-2\.0|BlueOak-1\.0\.0|WTFPL)$/;
const forbidden = /SSPL|BUSL|Elastic|GPL-2\.0-only|UNLICENSED|CC-BY-NC|proprietary/i;

export function isAllowed(expression) {
  if (typeof expression !== 'string' || forbidden.test(expression)) return false;
  const branches = expression.replaceAll(/[()]/g, '').split(/\s+OR\s+/);
  return branches.some((branch) => branch.split(/\s+AND\s+/).every((license) => allowed.test(license.trim())));
}
