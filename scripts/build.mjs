import { copyFile, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { stripTypeScriptTypes } from "node:module";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const frontendRoot = join(root, "frontend");
const srcRoot = join(frontendRoot, "src");
const distRoot = join(frontendRoot, "dist");
const assetsRoot = join(distRoot, "assets");
const referenceIconsRoot = join(root, "Референсы", "Иконки");
const chatIconsRoot = join(root, "Референсы", "Result", "Chat", "icons");
const assetVersion = "chat-details-files-1";

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await walk(fullPath));
    } else {
      files.push(fullPath);
    }
  }
  return files;
}

async function build() {
  await rm(distRoot, { recursive: true, force: true });
  await mkdir(assetsRoot, { recursive: true });
  await copyTextFile(join(frontendRoot, "index.html"), join(distRoot, "index.html"));
  await copyTextFile(join(srcRoot, "styles.css"), join(assetsRoot, "styles.css"));
  await copyReferenceIcons();
  await copySampleDocument();

  const files = await walk(srcRoot);
  for (const file of files) {
    if (extname(file) !== ".ts") continue;
    const relativePath = relative(srcRoot, file).replace(/\.ts$/, ".js");
    const outPath = join(assetsRoot, relativePath);
    const source = await readFile(file, "utf8");
    const stripped = stripTypeScriptTypes(source, { mode: "strip" })
      .replace(/from "(.+?)\.ts"/g, `from "$1.js?v=${assetVersion}"`)
      .replace(/from '(.+?)\.ts'/g, `from '$1.js?v=${assetVersion}'`);
    await mkdir(dirname(outPath), { recursive: true });
    await writeFile(outPath, stripped, "utf8");
  }
}

async function copyTextFile(from, to) {
  const content = await readFile(from, "utf8");
  await writeFile(to, content, "utf8");
}

async function copyReferenceIcons() {
  const iconsOut = join(assetsRoot, "icons");
  await mkdir(iconsOut, { recursive: true });
  const files = await readdir(referenceIconsRoot);
  for (const file of files) {
    if (extname(file).toLowerCase() !== ".svg") continue;
    await copyFile(join(referenceIconsRoot, file), join(iconsOut, file));
  }
  const chatFiles = await readdir(chatIconsRoot);
  for (const file of chatFiles) {
    if (extname(file).toLowerCase() !== ".svg") continue;
    await copyFile(join(chatIconsRoot, file), join(iconsOut, file));
  }
}

async function copySampleDocument() {
  await copyFile(join(root, "Пример ТЗ.docx"), join(distRoot, "Пример ТЗ.docx"));
}

build().then(() => {
  console.log("Frontend built into frontend/dist");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
