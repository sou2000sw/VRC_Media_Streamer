// ui/index.html から画面共有まわりの実コードを抜き出し、
// 「ポーリングが編集中の選択を巻き戻すか」を再現して検証する。
import fs from 'node:fs';

const html = fs.readFileSync('E:/Projects/VRC_Media_Streamer/ui/index.html', 'utf8');

// --- 1. 構造的な確認 -------------------------------------------------
const checks = {
  '変数 screenCaptureEditingUntil を宣言': /let screenCaptureEditingUntil = 0;/.test(html),
  'markScreenCaptureEditing を定義': /function markScreenCaptureEditing\(\)/.test(html),
  'sync に編集中ガードがある': /if \(Date\.now\(\) < screenCaptureEditingUntil\) return;/.test(html),
  '適用成功でガード解除': /screenCaptureEditingUntil = 0;[\s\S]{0,200}showToast\('画面共有設定を保存しました'/.test(html),
  'card に change を委譲': /scCard\.addEventListener\('change', markScreenCaptureEditing\);/.test(html),
  'card に input を委譲': /scCard\.addEventListener\('input', markScreenCaptureEditing\);/.test(html),
  'markScreenCaptureEditing がトップレベル': /^        function markScreenCaptureEditing\(\) \{$/m.test(html),
  'screenCaptureEditingUntil がトップレベル': /^        let screenCaptureEditingUntil = 0;$/m.test(html),
  '#screenCaptureCard は静的マークアップ': /id="screenCaptureCard"/.test(html),
};

const scriptBlocks = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const idxFn = scriptBlocks.findIndex(s => s.includes('function markScreenCaptureEditing()'));
const idxListener = scriptBlocks.findIndex(s => s.includes("scCard.addEventListener('change'"));
const idxSync = scriptBlocks.findIndex(s => s.includes('function syncScreenCaptureFromStatus'));
checks['委譲リスナ・関数定義・sync が同一 <script> 内'] = (idxFn !== -1 && idxFn === idxListener && idxFn === idxSync);

let allOk = true;
for (const [k, v] of Object.entries(checks)) {
  console.log((v ? '  OK   ' : '  FAIL ') + k);
  if (!v) allOk = false;
}

// --- 2. 挙動の再現 ---------------------------------------------------
function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error('not found: ' + name);
  let i = html.indexOf('{', start), depth = 0;
  for (let j = i; j < html.length; j++) {
    if (html[j] === '{') depth++;
    else if (html[j] === '}') { depth--; if (depth === 0) return html.slice(start, j + 1); }
  }
  throw new Error('unbalanced: ' + name);
}

const radios = [
  { value: 'display', checked: true },
  { value: 'window', checked: false },
];
const els = {
  screenCaptureDisplayIndex: { value: '0' },
  screenCaptureWindowTitle: { value: '' },
  screenCaptureResolution: { value: '1920x1080' },
  screenCaptureFramerate: { value: '30' },
  screenCaptureBitrateKbps: { value: '4000' },
  screenCaptureDrawMouse: { checked: true },
  screenCaptureDisplayGroup: { classList: { toggle() {}, add() {}, remove() {} } },
  screenCaptureWindowGroup: { classList: { toggle() {}, add() {}, remove() {} } },
};
const fakeDoc = {
  getElementsByName: () => radios,
  getElementById: (id) => els[id] || null,
};

const src = `
${extract('toggleScreenCaptureSourceFields')}
${extract('markScreenCaptureEditing')}
${extract('syncScreenCaptureFromStatus')}
return { sync: syncScreenCaptureFromStatus, mark: markScreenCaptureEditing,
         setEditingUntil(v) { screenCaptureEditingUntil = v; } };
`;
const factory = new Function('document', 'screenCaptureSourcesLoaded',
  'screenCaptureUserChangedAt', 'SCREEN_CAPTURE_EDIT_GRACE_MS',
  'let screenCaptureEditingUntil = 0;\n' + src);
const api = factory(fakeDoc, true, 0, 20000);

const serverStatus = {
  screen_capture_source_type: 'display',
  screen_capture_display_index: 0,
  screen_capture_window_title: '',
  screen_capture_width: 1920, screen_capture_height: 1080,
  screen_capture_framerate: 30, screen_capture_bitrate_kbps: 4000,
  screen_capture_draw_mouse: true,
};
const pick = (v) => radios.forEach(r => r.checked = (r.value === v));
const current = () => radios.find(r => r.checked).value;

console.log('\n--- 修正前の条件（編集中ガードが立っていない状態）---');
pick('window'); api.setEditingUntil(0);
api.sync(serverStatus);
const reverted = current() === 'display';
console.log('  window を選択 → ポーリング1回後: ' + current() + (reverted ? '  ← 巻き戻り（報告された不具合）' : ''));

console.log('\n--- 修正後（触った時点で markScreenCaptureEditing）---');
pick('window'); api.mark();
for (let i = 0; i < 20; i++) api.sync(serverStatus);
const kept = current() === 'window';
console.log('  window を選択 → ポーリング20回後: ' + current() + (kept ? '  ← 保持された' : '  ← まだ巻き戻る'));

console.log('\n--- 適用後はサーバー値へ追随するか ---');
api.setEditingUntil(0);
serverStatus.screen_capture_source_type = 'window';
api.sync(serverStatus);
const follows = current() === 'window';
console.log('  サーバーが window を返す → UI: ' + current() + (follows ? '  ← 追随OK' : '  ← 追随しない'));

const behaviourOk = reverted && kept && follows;
console.log('\nRESULT: ' + (allOk && behaviourOk ? 'PASS' : 'FAIL'));
process.exit(allOk && behaviourOk ? 0 : 1);
