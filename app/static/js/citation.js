/* GB/T 7714—2015 参考文献格式生成 */

/**
 * @param meta {author, title, year, publication, pages, url, publish_date}
 * @param type 'journal' | 'web' | 'book'
 */
export function gbt7714(meta, type) {
  const authors = formatAuthors(meta.author || "");
  const title = (meta.title || "未命名文献").trim();
  const year = (meta.year || "").trim();
  const dot = (s) => (s ? `${s.replace(/[.。]$/, "")}.` : "");

  if (type === "journal") {
    const pub = (meta.publication || "").trim().replace(/[.。]$/, "");
    const pages = meta.pages ? `:${meta.pages}` : "";
    const tail = pub && year ? `${pub}, ${year}${pages}.` : (year ? `${year}${pages}.` : (pub ? `${pub}.` : ""));
    return [authors && dot(authors), `${title}[J].`, tail].filter(Boolean).join(" ").replace(/\s+/g, " ");
  }
  if (type === "book") {
    return [authors && dot(authors), `${title}[M].`, meta.place && `${dot(meta.place)}`,
            meta.publisher && `${dot(meta.publisher)}`, year && `${year}.`]
      .filter(Boolean).join(" ").replace(/\.\./g, ".");
  }
  // web / 本地文件按电子文献
  const pubDate = meta.publish_date || (year ? `${year}-01-01` : "");
  const access = new Date().toISOString().slice(0, 10);
  const url = meta.url || "";
  return [
    authors ? dot(authors) : "",
    `${title}[EB/OL].`,
    pubDate ? `(${pubDate})` : "",
    `[${access}].`,
    url,
  ].filter(Boolean).join(" ").replace(/\s+/g, " ").replace(/\.\./g, ".");
}

/** 三个以上作者取前三 + 等；支持 、，; 分隔 */
function formatAuthors(raw) {
  const names = raw.split(/[、，,;；]/).map((s) => s.trim()).filter(Boolean);
  if (!names.length) return "";
  if (names.length <= 3) return names.join(", ");
  return names.slice(0, 3).join(", ") + ", 等";
}
