import { getBackendUrl } from '@/api/config'

/**
 * Render an Office.js failure into a message the LLM can actually act on.
 *
 * `OfficeExtension.Error.message` is frequently just "GeneralException", which
 * tells the agent (and us) nothing. The useful detail lives in `debugInfo`:
 * `code` names the failure class, `errorLocation` names the API that rejected,
 * and `statement` / `surroundingStatements` pinpoint the failing call inside
 * the batch. Office.js documents those two as never containing document data.
 *
 * `debugInfo.fullStatements` is deliberately NOT included: the typings warn it
 * carries "any potentially-sensitive information that was specified in the
 * request" — i.e. the user's document text — and this string is sent to the LLM.
 */
export function formatOfficeError(err: any): string {
  if (!err) return 'Error: Unknown error'

  const parts: string[] = [err.message || err.name || 'Unknown error']
  const info = err.debugInfo

  if (err.code && err.code !== err.message) parts.push(`code=${err.code}`)
  if (info?.errorLocation) parts.push(`at ${info.errorLocation}`)
  if (info?.message && info.message !== err.message) parts.push(`detail: ${info.message}`)
  if (info?.statement) parts.push(`failing statement: ${info.statement}`)
  if (info?.surroundingStatements?.length) {
    parts.push(`context: ${info.surroundingStatements.join(' | ')}`)
  }
  if (typeof info?.innerError === 'string') parts.push(`inner: ${info.innerError}`)
  else if (info?.innerError?.message) parts.push(`inner: ${info.innerError.message}`)

  return `Error: ${parts.join(' — ')}`
}

/**
 * Sanitize text returned from Word's body.text / range.text.
 * Converts Word-specific control characters to standard equivalents so LLMs
 * receive clean, predictable text.
 */
function sanitizeWordText(text: string): string {
  return text
    .replace(/\u000b/g, '\n') // vertical tab (in-cell line break) -> newline
    .replace(/\r\n/g, '\n') // Windows CRLF -> LF
    .replace(/\r/g, '\n') // remaining CR -> LF
    .replace(/[\x00-\x08\x0c\x0e-\x1f\x7f]/g, '') // strip C0 controls except \t(\x09) and \n(\x0a)
}

/**
 * Strip unambiguous markdown syntax from text before Word insertion.
 * LLMs sometimes emit markdown despite explicit "no markdown" instructions.
 * Only runs on text >= 150 chars (short text is never markdown dumps).
 * Only strips patterns with near-zero false-positive risk.
 */
function stripMarkdown(text: string): string {
  if (text.length < 150) return text

  const original = text
  const lines = text.split('\n')
  const result: string[] = []
  let inCodeFence = false

  for (const line of lines) {
    // Code fences: ```lang or ~~~ — drop fence lines, keep content
    if (/^\s*(`{3,}|~{3,})/.test(line)) {
      inCodeFence = !inCodeFence
      continue
    }
    if (inCodeFence) {
      result.push(line)
      continue
    }

    // Horizontal rules: ---, ***, ___ (3+ repeated, optionally spaced)
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) continue

    let stripped = line

    // Heading markers: ^#{1,6} text → text
    stripped = stripped.replace(/^(\s*)#{1,6}\s+/, '$1')

    // Images: ![alt](url) → alt (before links to avoid partial match)
    stripped = stripped.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')

    // Links: [text](url) → text
    stripped = stripped.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')

    // Strikethrough: ~~text~~ → text
    stripped = stripped.replace(/~~(.+?)~~/g, '$1')

    // Bold+italic: ***text*** or ___text___ → text
    stripped = stripped.replace(/\*{3}(.+?)\*{3}/g, '$1')
    stripped = stripped.replace(/_{3}(.+?)_{3}/g, '$1')

    // Bold: **text** or __text__ → text
    stripped = stripped.replace(/\*{2}(.+?)\*{2}/g, '$1')
    stripped = stripped.replace(/_{2}(.+?)_{2}/g, '$1')

    result.push(stripped)
  }

  const cleaned = result.join('\n')
  if (cleaned !== original) {
    console.warn(
      '[WordTools] Stripped markdown from tool argument.\n  Before:',
      original.slice(0, 200),
      '\n  After:',
      cleaned.slice(0, 200),
    )
  }
  return cleaned
}

interface ProxiedImage {
  base64: string
  /** Content type actually handed to Word (always one Word can decode). */
  contentType: string
  /** Content type the origin server served, before any transcoding. */
  sourceContentType: string
  converted: boolean
}

/** Formats Word's inline-picture decoder handles. Mirrors WORD_NATIVE_TYPES in image_proxy.py. */
const WORD_NATIVE_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/bmp', 'image/tiff'])

/** Fetch a remote image through the backend proxy. Throws with the backend's own message. */
async function fetchImageViaProxy(imageUrl: string): Promise<ProxiedImage> {
  const endpoint = `${getBackendUrl()}/api/proxy/image?url=${encodeURIComponent(imageUrl)}`
  let res: Response
  try {
    res = await fetch(endpoint)
  } catch (e) {
    throw new Error(`backend image proxy unreachable at ${endpoint} (${(e as Error).message})`)
  }
  if (!res.ok) {
    let detail = await res.text()
    try {
      detail = JSON.parse(detail).detail ?? detail
    } catch {
      // Not JSON — the raw body is the best detail available.
    }
    throw new Error(detail)
  }
  return res.json()
}

async function blobToBase64(blob: Blob): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => resolve((reader.result as string).split(',')[1])
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the image data'))
    reader.readAsDataURL(blob)
  })
}

/**
 * Resolve an image URL to base64 Word can decode, trying the browser first and
 * the backend proxy second.
 *
 * Neither route alone is sufficient, and the two fail on disjoint sets of hosts:
 *   - The browser fetch is blocked by CORS (most image hosts send no
 *     `Access-Control-Allow-Origin`) and by hotlink protection.
 *   - The backend fetch is blocked by hosts that refuse server-side clients on
 *     principle — Wikimedia answers 403 with a link to its robot policy, while
 *     serving the same file to a browser without complaint.
 * Trying the browser first also keeps the common case off the server entirely.
 *
 * The proxy is used regardless when the browser gets a format Word cannot
 * decode (WEBP, AVIF), since only the backend can transcode it to PNG.
 */
async function fetchImageAsBase64(imageUrl: string): Promise<ProxiedImage> {
  let directError = ''
  try {
    const response = await fetch(imageUrl)
    if (!response.ok) throw new Error(`HTTP ${response.status} ${response.statusText}`)
    const blob = await response.blob()
    const type = blob.type.split(';')[0].trim().toLowerCase()
    if (WORD_NATIVE_IMAGE_TYPES.has(type)) {
      return {
        base64: await blobToBase64(blob),
        contentType: type,
        sourceContentType: type,
        converted: false,
      }
    }
    directError = `direct fetch returned ${type || 'an unknown type'}, which Word cannot decode`
  } catch (e) {
    directError = (e as Error).message
  }

  console.warn(`[WordTools] Direct image fetch fell back to the backend proxy: ${directError}`)
  try {
    return await fetchImageViaProxy(imageUrl)
  } catch (e) {
    throw new Error(
      `Could not load image "${imageUrl}". Browser fetch: ${directError}. ` +
        `Backend proxy: ${(e as Error).message}`,
    )
  }
}

/**
 * Normalize line endings, including literal two-character \n sequences that
 * LLMs sometimes emit instead of real newline characters.
 */
function normalizeLineBreaks(text: string): string {
  return text
    .replace(/\\n/g, '\n') // literal backslash+n → newline
    .replace(/\r\n/g, '\n') // Windows CRLF → LF
    .replace(/\r/g, '\n') // old Mac CR → LF
}

/**
 * Insert text into a Word range, splitting on \n to create proper paragraphs,
 * and return a collapsed range at the end of the inserted content so the caller
 * can park the cursor there.
 *
 * Each extra line is chained off the paragraph before it. Anchoring them all to
 * the original `range` instead — which an earlier version did — inserts every
 * new paragraph immediately after that same fixed point, so the lines come out
 * reversed and line 1 is left stranded at the far end of the run.
 *
 * keepStyle=false (default): subsequent paragraphs reset to Normal to prevent
 * heading style bleeding. keepStyle=true: style inherits from first paragraph.
 */
async function insertTextSafe(
  context: Word.RequestContext,
  range: Word.Range,
  text: string,
  location: Word.InsertLocation,
  keepStyle = false,
): Promise<Word.Range> {
  const lines = normalizeLineBreaks(text).split('\n')
  const firstRange = range.insertText(lines[0], location)

  const created: Word.Paragraph[] = []
  let previous: Word.Paragraph | null = null
  for (let i = 1; i < lines.length; i++) {
    const para = previous
      ? previous.insertParagraph(lines[i], 'After')
      : firstRange.insertParagraph(lines[i], 'After')
    if (!keepStyle) para.styleBuiltIn = 'Normal'
    created.push(para)
    previous = para
  }

  // Line 1 either merged into an existing paragraph (cursor sitting inside
  // text) or became a paragraph of its own (Word starts a new item when the
  // cursor is at the end of a list item). Only the second case is ours to
  // detach, and a paragraph whose entire text is the line we just wrote cannot
  // be holding anything that existed before.
  const firstParas = firstRange.paragraphs
  firstParas.load('items/text,items/isListItem')
  await context.sync()
  const ownFirst: Word.Paragraph[] = []
  const firstLine = lines[0].trim()
  if (firstLine.length > 0) {
    for (const p of firstParas.items) {
      if (sanitizeWordText(p.text).trim() === firstLine) ownFirst.push(p)
    }
  }

  await detachFromInheritedList(context, [...ownFirst, ...created])

  const last = previous ?? ownFirst[ownFirst.length - 1]
  return last ? last.getRange('End') : firstRange.getRange('End')
}

/**
 * Resolve the paragraph a block-level insertion should hang off.
 *
 * Paragraphs, lists, tables, page breaks and pictures are block content: they
 * cannot live inside another paragraph. Asking Word to put one "After" a range
 * that covers only part of a paragraph makes it split that paragraph at the
 * range end and wedge the block into the gap — select three words of a sentence
 * and insert a paragraph, and the sentence is torn in two with the new content
 * (and everything inserted after it) sitting in the middle.
 *
 * Anchoring to the containing paragraph instead is what the tool contracts
 * promise: "after the cursor" means after the paragraph the cursor is in.
 * Syncs once; the caller still owns the final sync.
 */
async function getBlockAnchor(
  context: Word.RequestContext,
  range: Word.Range,
  location: string,
): Promise<Word.Paragraph> {
  const paragraphs = range.paragraphs
  paragraphs.load('items')
  await context.sync()
  if (paragraphs.items.length === 0) {
    throw new Error(
      'Could not resolve the cursor to a paragraph in the document. ' +
        'Click inside the document body and try again.',
    )
  }
  return location === 'Before' || location === 'Start'
    ? paragraphs.items[0]
    : paragraphs.items[paragraphs.items.length - 1]
}

/**
 * Word carries list membership onto a paragraph inserted adjacent to an existing
 * list, so plain content added right after one silently becomes its next item and
 * renumbers the list. The text and paragraph tools promise plain content, so undo
 * that: drop the membership and the indentation the list left behind (a list
 * level's indent IS the paragraph indent — see List.setLevelIndents).
 *
 * Syncs once to read `isListItem`; the caller still owns the final sync.
 */
async function detachFromInheritedList(
  context: Word.RequestContext,
  paragraphs: Word.Paragraph[],
): Promise<void> {
  if (paragraphs.length === 0) return
  paragraphs.forEach(p => p.load('isListItem'))
  await context.sync()
  for (const p of paragraphs) {
    if (p.isListItem) {
      p.detachFromList()
      p.leftIndent = 0
      p.firstLineIndent = 0
    }
  }
}

// ═══════════════════════════════════════════════════════════
//  Track-change OOXML infrastructure
//
//  Key architecture:
//    parseOoxml()              → cleanText + boundaries[]
//    resolveAnchors()          → boundary-safe search strings
//    resolveCleanTextToRange() → single occurrence → Word.Range
//    resolveAllOccurrences()   → ALL occurrences → Word.Range[]
//    trackedReplace()          → changeTrackingMode wrapper
// ═══════════════════════════════════════════════════════════

const MIN_ANCHOR_LEN = 12

interface ParsedDocument {
  cleanText: string
  /**
   * Segment breaks: every position where a `body.search()` string must not be
   * allowed to span. This is the union of real paragraph breaks and the "soft"
   * breaks left by tracked deletions and comment anchors — Word will not match
   * a search string across either, so anchor resolution must treat them alike.
   */
  boundaries: boolean[]
  /**
   * Paragraph and line breaks only. This is what the reader tools render as
   * `\n`. Keeping it apart from `boundaries` is what stops a tracked deletion
   * or a comment from being reported to the LLM as a paragraph split that does
   * not exist in the document.
   */
  hardBreaks: boolean[]
}

interface AnchorResult {
  startAnchor: string
  endAnchor: string
  isSingle: boolean
  startOffset: number
  endOffset: number
}

interface OccurrenceInfo {
  cleanIdx: number
  end: number
  isSingle: boolean
  anchors: AnchorResult | null
  positionIndex: number
}

interface FindMatch {
  index: number
  contextBefore: string
  contextAfter: string
  hasBoundaries: boolean
}

function parseOoxml(ooxml: string): ParsedDocument {
  const parser = new DOMParser()
  const xmlDoc = parser.parseFromString(ooxml, 'application/xml')

  let cleanText = ''
  const boundaries: boolean[] = []
  const hardBreaks: boolean[] = []
  let pendingBreak = false
  let pendingHardBreak = false
  let inFieldInstruction = false
  let fieldDepth = 0

  function addChar(ch: string) {
    boundaries.push(pendingBreak && cleanText.length > 0)
    hardBreaks.push(pendingHardBreak && cleanText.length > 0)
    pendingBreak = false
    pendingHardBreak = false
    cleanText += ch
  }

  /** A real paragraph/line break: blocks search spanning AND renders as \n. */
  function markHardBreak() {
    if (cleanText.length > 0) {
      pendingBreak = true
      pendingHardBreak = true
    }
  }

  function walk(el: Element) {
    for (const child of Array.from(el.childNodes)) {
      if (child.nodeType !== 1) continue
      const ln = (child as Element).localName

      if (ln === 'del' || ln === 'comment') {
        // Soft break only. Word cannot match a search string across a tracked
        // deletion or a comment anchor, so anchor resolution has to stop here —
        // but the surrounding text is still one continuous paragraph, and
        // rendering a \n here would report a paragraph split that isn't real.
        pendingBreak = true
        continue
      }

      if (ln === 'fldChar') {
        const type = (child as Element).getAttribute('w:fldCharType')
        if (type === 'begin') {
          fieldDepth++
          inFieldInstruction = true
        } else if (type === 'separate') {
          inFieldInstruction = false
        } else if (type === 'end') {
          fieldDepth = Math.max(0, fieldDepth - 1)
          if (fieldDepth === 0) inFieldInstruction = false
        }
        continue
      }

      if (ln === 'instrText') continue

      if (ln === 't') {
        if (!inFieldInstruction) {
          for (const ch of child.textContent!) addChar(ch)
        }
        continue
      }

      // Paragraph boundary — mark break then recurse into runs
      if (ln === 'p') {
        markHardBreak()
        walk(child as Element)
        continue
      }

      // Explicit line break (Shift+Enter)
      if (ln === 'br') {
        markHardBreak()
        continue
      }

      // Tab character (would otherwise be silently dropped)
      if (ln === 'tab') {
        addChar('\t')
        continue
      }

      // Table structure — treat each cell as a separate segment so that anchor
      // resolution never builds an expandTo() range that crosses cell walls
      // (Word rejects such ranges with GeneralException on insertText).
      if (ln === 'tbl' || ln === 'tr' || ln === 'tc') {
        markHardBreak()
        walk(child as Element)
        markHardBreak()
        continue
      }

      walk(child as Element)
    }
  }

  walk(xmlDoc.documentElement)
  return { cleanText, boundaries, hardBreaks }
}

/** Convert cleanText into display text with \n at real paragraph boundaries. */
function toDisplayText(parsed: ParsedDocument): string {
  return sliceToDisplay(parsed.cleanText, parsed.hardBreaks, 0, parsed.cleanText.length)
}

/** Convert a cleanText slice [from, to) into display text with \n at hard breaks. */
function sliceToDisplay(cleanText: string, hardBreaks: boolean[], from: number, to: number): string {
  let result = ''
  for (let i = from; i < to && i < cleanText.length; i++) {
    if (hardBreaks[i]) result += '\n'
    result += cleanText[i]
  }
  return result
}

/** Prepare search text for use with Word.body.search().
 *  Strips newlines (cleanText has none) and throws on characters body.search()
 *  cannot handle, so the LLM receives a clear actionable error instead of
 *  an opaque GeneralException. */
function prepareSearchText(raw: string, paramName = 'searchText'): string {
  if (typeof raw !== 'string' || raw.length === 0) {
    throw new Error(`${paramName} must be a non-empty string`)
  }
  // Strip all newline variants (LLM sees \n but cleanText/body.search have none)
  const noNewlines = raw.replace(/\r\n|\r|\n/g, '')
  // Reject control characters that body.search() cannot handle
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(noNewlines)) {
    throw new Error(
      `${paramName} contains unsupported control characters that Word.search cannot match. Provide a plain-text query.`,
    )
  }
  // Reject tab, NBSP and zero-width chars – they appear in cleanText (from table
  // cells, formatted content) but body.search() rejects them with GeneralException
  const m = noNewlines.match(/[\t ­​-‍﻿]/)
  if (m) {
    const char = m[0]
    const label =
      char === '\t' ? 'TAB (\\t)' :
      char === ' ' ? 'NBSP (U+00A0)' :
      char === '­' ? 'SOFT HYPHEN (U+00AD)' :
      `ZERO-WIDTH (U+${char.charCodeAt(0).toString(16).toUpperCase().padStart(4, '0')})`
    throw new Error(
      `${paramName} contains ${label} which Word.search cannot match. ` +
      `If the text was copied from a table or formatted region, search for a ` +
      `shorter phrase from inside a single cell or paragraph.`,
    )
  }
  return noNewlines
}

function findContiguousRange(boundaries: boolean[], pos: number): { segStart: number; segEnd: number } {
  let segStart = pos
  while (segStart > 0 && !boundaries[segStart]) segStart--
  let segEnd = pos
  while (segEnd < boundaries.length - 1 && !boundaries[segEnd + 1]) segEnd++
  return { segStart, segEnd }
}

function countOccurrences(haystack: string, needle: string): number {
  let count = 0
  let pos = 0
  while (true) {
    pos = haystack.indexOf(needle, pos)
    if (pos === -1) break
    count++
    pos++
  }
  return count
}

/** Build an anchor for a single-segment occurrence that body.search() failed to
 *  match by extending the match into its containing segment until the substring
 *  is unique in cleanText (or segment edges are reached). */
function synthesiseUniqueAnchor(
  cleanText: string,
  boundaries: boolean[],
  start: number,
  end: number,
): AnchorResult {
  const { segStart, segEnd } = findContiguousRange(boundaries, start)
  let from = start
  let to = end
  while (countOccurrences(cleanText, cleanText.slice(from, to + 1)) > 1) {
    if (from > segStart) from--
    else if (to < segEnd) to++
    else break
  }
  const anchor = cleanText.slice(from, to + 1)
  return {
    startAnchor: anchor,
    endAnchor: anchor,
    isSingle: true,
    startOffset: start - from,
    endOffset: to - end,
  }
}

function resolveAnchors(cleanText: string, boundaries: boolean[], start: number, end: number): AnchorResult {
  const segments: [number, number][] = []
  let segBegin = start
  for (let i = start + 1; i <= end; i++) {
    if (boundaries[i]) {
      segments.push([segBegin, i - 1])
      segBegin = i
    }
  }
  segments.push([segBegin, end])

  if (segments.length === 1) {
    return {
      startAnchor: cleanText.slice(start, end + 1),
      endAnchor: cleanText.slice(start, end + 1),
      isSingle: true,
      startOffset: 0,
      endOffset: 0,
    }
  }

  const [, sTo] = segments[0]
  let sFrom = segments[0][0]
  let startOffset = 0
  if (sTo - sFrom + 1 < MIN_ANCHOR_LEN) {
    const { segStart: cs } = findContiguousRange(boundaries, start)
    const extend = Math.min(start - cs, MIN_ANCHOR_LEN - (sTo - sFrom + 1))
    if (extend > 0) {
      sFrom = start - extend
      startOffset = extend
    }
  }
  const startAnchor = cleanText.slice(sFrom, sTo + 1)

  const [eFrom] = segments[segments.length - 1]
  let eTo = segments[segments.length - 1][1]
  let endOffset = 0
  if (eTo - eFrom + 1 < MIN_ANCHOR_LEN) {
    const { segEnd: ce } = findContiguousRange(boundaries, end)
    const extend = Math.min(ce - end, MIN_ANCHOR_LEN - (eTo - eFrom + 1))
    if (extend > 0) {
      eTo = end + extend
      endOffset = extend
    }
  }
  const endAnchor = cleanText.slice(eFrom, eTo + 1)

  return { startAnchor, endAnchor, isSingle: false, startOffset, endOffset }
}

function isOfficeError(e: unknown): boolean {
  return !!e && typeof e === 'object' && (
    (e as any).name === 'OfficeExtension.Error' ||
    typeof (e as any).code === 'string'
  )
}

function enrichOfficeError(e: unknown, operation: string, snippet: string): Error {
  const code = isOfficeError(e) ? ((e as any).code ?? 'GeneralException') : String(e)
  const err = new Error(
    `Word.${operation} failed for "${snippet.slice(0, 80)}${snippet.length > 80 ? '…' : ''}" ` +
    `(${code}). Likely cause: unsupported character, invalid range (e.g. crossing a ` +
    `table cell wall), or a concurrent document change.`,
    { cause: e },
  )
  return err
}

async function searchBody(
  context: Word.RequestContext,
  body: Word.Body,
  text: string,
  label: string,
): Promise<Word.Range[] | null> {
  try {
    const r1 = body.search(text, { matchCase: true, matchWildcards: false })
    r1.load('items')
    await context.sync()
    if (r1.items.length > 0) {
      console.log(`  [WordTools] ${label}: ${r1.items.length} match(es)`)
      return r1.items
    }

    const r2 = body.search(text, { matchCase: false, matchWildcards: false })
    r2.load('items')
    await context.sync()
    if (r2.items.length > 0) {
      console.warn(`  [WordTools] ${label}: ${r2.items.length} match(es) (case-insensitive)`)
      return r2.items
    }

    console.error(`  [WordTools] ${label}: NOT FOUND — "${text.slice(0, 60)}"`)
    return null
  } catch (e) {
    if (isOfficeError(e)) throw enrichOfficeError(e, 'search', text)
    throw e
  }
}

async function searchWithinRange(
  context: Word.RequestContext,
  range: Word.Range,
  text: string,
  label: string,
): Promise<Word.Range[] | null> {
  try {
    const r = range.search(text, { matchCase: true, matchWildcards: false })
    r.load('items')
    await context.sync()
    if (r.items.length > 0) return r.items
    console.error(`  [WordTools] ${label}: NOT FOUND within range`)
    return null
  } catch (e) {
    if (isOfficeError(e)) throw enrichOfficeError(e, 'search', text)
    throw e
  }
}

async function trimAnchorRange(
  context: Word.RequestContext,
  range: Word.Range,
  originalSegText: string,
  offset: number,
  side: 'start' | 'end',
): Promise<Word.Range> {
  if (offset === 0) return range
  const items = await searchWithinRange(context, range, originalSegText, `trim-${side}`)
  if (!items) {
    console.warn(`  [WordTools] trim-${side}: fallback to untrimmed`)
    return range
  }
  return side === 'start' ? items[items.length - 1] : items[0]
}

async function disambiguateAnchors(
  context: Word.RequestContext,
  startItems: Word.Range[],
  endItems: Word.Range[],
): Promise<{ startRange: Word.Range; endRange: Word.Range } | null> {
  if (startItems.length === 1 && endItems.length === 1) {
    return { startRange: startItems[0], endRange: endItems[0] }
  }

  console.log(`  [WordTools] Disambiguating: ${startItems.length} start × ${endItems.length} end`)

  if (startItems.length <= endItems.length) {
    for (const sRange of startItems) {
      const cmps = endItems.map(er => sRange.compareLocationWith(er))
      await context.sync()
      for (let i = 0; i < cmps.length; i++) {
        if (cmps[i].value === 'Before' || cmps[i].value === 'AdjacentBefore') {
          return { startRange: sRange, endRange: endItems[i] }
        }
      }
    }
  } else {
    for (const eRange of endItems) {
      const cmps = startItems.map(sr => sr.compareLocationWith(eRange))
      await context.sync()
      for (let i = cmps.length - 1; i >= 0; i--) {
        if (cmps[i].value === 'Before' || cmps[i].value === 'AdjacentBefore') {
          return { startRange: startItems[i], endRange: eRange }
        }
      }
    }
  }

  console.error('  [WordTools] Failed to pair anchors.')
  return null
}

async function resolveCleanTextToRange(
  context: Word.RequestContext,
  body: Word.Body,
  parsed: ParsedDocument,
  searchText: string,
): Promise<{ range: Word.Range; cleanIdx: number } | null> {
  const { cleanText, boundaries } = parsed
  const idx = cleanText.indexOf(searchText)
  if (idx === -1) return null

  const end = idx + searchText.length - 1
  const anchors = resolveAnchors(cleanText, boundaries, idx, end)

  if (anchors.isSingle) {
    const items = await searchBody(context, body, anchors.startAnchor, 'anchor')
    if (!items) return null
    return { range: items[0], cleanIdx: idx }
  }

  const startItems = await searchBody(context, body, anchors.startAnchor, 'startAnchor')
  if (!startItems) return null
  const endItems = await searchBody(context, body, anchors.endAnchor, 'endAnchor')
  if (!endItems) return null

  const pair = await disambiguateAnchors(context, startItems, endItems)
  if (!pair) return null

  let trimmedStart = pair.startRange
  let trimmedEnd = pair.endRange

  if (anchors.startOffset > 0) {
    trimmedStart = await trimAnchorRange(
      context,
      pair.startRange,
      anchors.startAnchor.slice(anchors.startOffset),
      anchors.startOffset,
      'start',
    )
  }
  if (anchors.endOffset > 0) {
    trimmedEnd = await trimAnchorRange(
      context,
      pair.endRange,
      anchors.endAnchor.slice(0, anchors.endAnchor.length - anchors.endOffset),
      anchors.endOffset,
      'end',
    )
  }

  return { range: trimmedStart.expandTo(trimmedEnd), cleanIdx: idx }
}

async function resolveAllOccurrences(
  context: Word.RequestContext,
  body: Word.Body,
  parsed: ParsedDocument,
  searchText: string,
): Promise<Word.Range[]> {
  const { cleanText, boundaries } = parsed

  // Find all cleanText positions
  const positions: number[] = []
  let pos = 0
  while (true) {
    const idx = cleanText.indexOf(searchText, pos)
    if (idx === -1) break
    positions.push(idx)
    pos = idx + 1
  }
  if (positions.length === 0) return []
  console.log(`  [WordTools] Found ${positions.length} cleanText occurrence(s)`)

  // Classify each occurrence
  const occurrences: OccurrenceInfo[] = positions.map((idx, pi) => {
    const end = idx + searchText.length - 1
    let hasBoundary = false
    for (let i = idx + 1; i <= end; i++) {
      if (boundaries[i]) {
        hasBoundary = true
        break
      }
    }
    return {
      cleanIdx: idx,
      end,
      isSingle: !hasBoundary,
      anchors: hasBoundary ? resolveAnchors(cleanText, boundaries, idx, end) : null,
      positionIndex: pi,
    }
  })

  const singleOccs = occurrences.filter(o => o.isSingle)
  const multiOccs = occurrences.filter(o => !o.isSingle)
  console.log(`  [WordTools] Single-segment: ${singleOccs.length}, Multi-segment: ${multiOccs.length}`)

  // Resolve single-segment occurrences.
  // Fast path: one body.search() call. Valid ONLY when counts match exactly —
  // if counts differ the ordinal pairing would silently replace the wrong text.
  const resolved: { positionIndex: number; range: Word.Range }[] = []

  if (singleOccs.length > 0) {
    const items = await searchBody(context, body, searchText, 'single-seg-all')
    const fastPathOk = items !== null && items.length === singleOccs.length

    if (fastPathOk) {
      for (let i = 0; i < items!.length; i++) {
        resolved.push({ positionIndex: singleOccs[i].positionIndex, range: items![i] })
      }
    } else {
      // Count mismatch: body.search doesn't agree with cleanText positions.
      // Fall back to per-occurrence anchor resolution to avoid wrong-index pairing.
      const got = items?.length ?? 0
      console.warn(
        `  [WordTools] body.search returned ${got} but cleanText has ${singleOccs.length}. ` +
        `Falling back to per-occurrence anchor resolution.`,
      )
      for (const occ of singleOccs) {
        occ.isSingle = false
        occ.anchors = synthesiseUniqueAnchor(cleanText, boundaries, occ.cleanIdx, occ.end)
      }
      multiOccs.push(...singleOccs)
      multiOccs.sort((a, b) => a.positionIndex - b.positionIndex)
    }
  }

  // Resolve multi-segment: individually with anchors
  for (const occ of multiOccs) {
    const anchors = occ.anchors!

    const startItems = await searchBody(context, body, anchors.startAnchor, 'ms-start')
    if (!startItems) continue
    const endItems = await searchBody(context, body, anchors.endAnchor, 'ms-end')
    if (!endItems) continue

    // Use previously resolved range to filter candidates
    let filteredStart = startItems
    const prevResolved = resolved
      .filter(r => r.positionIndex < occ.positionIndex)
      .sort((a, b) => b.positionIndex - a.positionIndex)

    if (prevResolved.length > 0 && startItems.length > 1) {
      const prevRange = prevResolved[0].range
      const cmps = startItems.map(sr => prevRange.compareLocationWith(sr))
      await context.sync()
      const afterPrev = startItems.filter((_, i) => cmps[i].value === 'Before' || cmps[i].value === 'AdjacentBefore')
      if (afterPrev.length > 0) filteredStart = afterPrev
    }

    const pair = await disambiguateAnchors(context, filteredStart, endItems)
    if (!pair) continue

    let trimmedStart = pair.startRange
    let trimmedEnd = pair.endRange

    if (anchors.startOffset > 0) {
      trimmedStart = await trimAnchorRange(
        context,
        pair.startRange,
        anchors.startAnchor.slice(anchors.startOffset),
        anchors.startOffset,
        'start',
      )
    }
    if (anchors.endOffset > 0) {
      trimmedEnd = await trimAnchorRange(
        context,
        pair.endRange,
        anchors.endAnchor.slice(0, anchors.endAnchor.length - anchors.endOffset),
        anchors.endOffset,
        'end',
      )
    }

    resolved.push({
      positionIndex: occ.positionIndex,
      range: trimmedStart.expandTo(trimmedEnd),
    })
  }

  // Return in document order
  resolved.sort((a, b) => a.positionIndex - b.positionIndex)
  console.log(`  [WordTools] Resolved ${resolved.length} of ${positions.length} occurrences to ranges`)
  return resolved.map(r => r.range)
}

async function getDocumentParsed(context: Word.RequestContext): Promise<{ body: Word.Body; parsed: ParsedDocument }> {
  const body = context.document.body
  const ooxmlResult = body.getOoxml()
  await context.sync()
  const parsed = parseOoxml(ooxmlResult.value)
  console.log(
    `[WordTools] Parsed: ${parsed.cleanText.length} chars, ` + `${parsed.boundaries.filter(Boolean).length} boundaries`,
  )
  return { body, parsed }
}

async function trackedReplace(
  context: Word.RequestContext,
  range: Word.Range,
  newText: string,
  keepStyle = false,
): Promise<void> {
  newText = normalizeLineBreaks(newText)
  context.document.load('changeTrackingMode')
  await context.sync()
  const saved = context.document.changeTrackingMode
  context.document.changeTrackingMode = Word.ChangeTrackingMode.trackAll
  try {
    range.insertText(newText, Word.InsertLocation.replace)
    await context.sync()
  } catch (e) {
    context.document.changeTrackingMode = saved
    if (isOfficeError(e)) throw enrichOfficeError(e, 'insertText', newText)
    throw e
  }
  context.document.changeTrackingMode = saved
  // Reset style on non-first paragraphs to prevent heading style bleeding
  if (!keepStyle && newText.includes('\n')) {
    const paras = range.paragraphs
    paras.load('items')
    await context.sync()
    for (let i = 1; i < paras.items.length; i++) {
      paras.items[i].styleBuiltIn = 'Normal'
    }
  }
  await context.sync()
}

/**
 * Wrapper around resolveAllOccurrences that respects the matchCase parameter.
 * When matchCase=false, finds positions via case-insensitive search on cleanText,
 * extracts actual-cased slices, groups by variant, resolves each, and merges.
 */
async function resolveAllOccurrencesCaseAware(
  context: Word.RequestContext,
  body: Word.Body,
  parsed: ParsedDocument,
  searchText: string,
  matchCase: boolean,
): Promise<Word.Range[]> {
  if (matchCase) {
    return resolveAllOccurrences(context, body, parsed, searchText)
  }

  const lower = parsed.cleanText.toLowerCase()
  const needle = searchText.toLowerCase()
  const positions: number[] = []
  let pos = 0
  while (true) {
    const idx = lower.indexOf(needle, pos)
    if (idx === -1) break
    positions.push(idx)
    pos = idx + 1
  }
  if (positions.length === 0) return []

  // Group positions by actual text (preserving original case)
  const groups = new Map<string, number[]>()
  for (const p of positions) {
    const actual = parsed.cleanText.slice(p, p + searchText.length)
    if (!groups.has(actual)) groups.set(actual, [])
    groups.get(actual)!.push(p)
  }

  // Single casing variant — resolve normally
  if (groups.size === 1) {
    const actualText = groups.keys().next().value!
    return resolveAllOccurrences(context, body, parsed, actualText)
  }

  // Multiple case variants — resolve each group and merge in document order
  const allRanges: { pos: number; range: Word.Range }[] = []
  for (const [actualText] of groups) {
    const ranges = await resolveAllOccurrences(context, body, parsed, actualText)
    const variantPositions = groups.get(actualText)!
    for (let i = 0; i < Math.min(ranges.length, variantPositions.length); i++) {
      allRanges.push({ pos: variantPositions[i], range: ranges[i] })
    }
  }
  allRanges.sort((a, b) => a.pos - b.pos)
  return allRanges.map(r => r.range)
}

export const wordToolExecutors = {
  getSelectedText: async () => {
    return Word.run(async context => {
      const sel = context.document.getSelection()
      // Range.getOoxml() throws GeneralException on a collapsed (empty) selection
      // instead of returning empty OOXML, so emptiness must be settled in its own
      // sync round-trip before getOoxml() is ever queued into the batch.
      sel.load('text')
      await context.sync()
      // An empty string is indistinguishable from a tool that produced no
      // output, so say it in words the LLM can act on.
      if ((sel.text ?? '').length === 0) {
        return '(nothing is selected — the cursor is collapsed at a single point)'
      }

      const ooxmlResult = sel.getOoxml()
      await context.sync()
      const parsed = parseOoxml(ooxmlResult.value)
      return sanitizeWordText(toDisplayText(parsed))
    })
  },

  getDocumentContent: async () => {
    return Word.run(async context => {
      const { parsed } = await getDocumentParsed(context)
      return sanitizeWordText(toDisplayText(parsed))
    })
  },

  insertText: async (args: any) => {
    const { text: rawText, location = 'End', keepStyle = false } = args
    const text = stripMarkdown(rawText)
    return Word.run(async context => {
      const range = context.document.getSelection()
      const endOfInsert = await insertTextSafe(context, range, text, location as Word.InsertLocation, keepStyle)
      // Move cursor to end of inserted content so consecutive calls
      // insert in correct order instead of reversing
      endOfInsert.select()
      await context.sync()
      return `Successfully inserted text at ${location}`
    })
  },

  replaceSelectedText: async (args: any) => {
    const { newText: rawNewText, keepStyle = false } = args
    const newText = stripMarkdown(rawNewText)
    return Word.run(async context => {
      const selection = context.document.getSelection()
      selection.load('text')
      await context.sync()

      if (!selection.text || selection.text.length === 0) {
        throw new Error('Nothing is selected.')
      }

      await trackedReplace(context, selection, newText, keepStyle)
      return 'Successfully replaced selected text'
    })
  },

  appendText: async (args: any) => {
    const { text: rawText, keepStyle = false } = args
    const text = stripMarkdown(rawText)
    return Word.run(async context => {
      const body = context.document.body
      const paragraphs = body.paragraphs
      paragraphs.load('items/text,items/isListItem')
      await context.sync()

      // "Append to the end of the document" has to start a new block.
      // `body.getRange('End')` is a collapsed point *inside* the last
      // paragraph, so writing there extends it instead — and when that
      // paragraph is a list item, the appended text silently becomes one more
      // item of the list ("EtaAPPENDED LINE ONE"). Only a trailing empty
      // non-list paragraph is safe to write into directly; anything else gets
      // a fresh paragraph of its own.
      const last = paragraphs.items[paragraphs.items.length - 1]
      let range: Word.Range
      if (last && (last.isListItem || sanitizeWordText(last.text).trim().length > 0)) {
        const carrier = last.insertParagraph('', 'After')
        await detachFromInheritedList(context, [carrier])
        range = carrier.getRange('End')
      } else {
        range = body.getRange('End')
      }

      const endOfInsert = await insertTextSafe(context, range, text, 'End', keepStyle)
      // Leave the cursor at the end of what was appended. Anything inserted
      // next then continues from there instead of jumping back to wherever the
      // cursor happened to be before the append.
      endOfInsert.select()
      await context.sync()
      return 'Successfully appended text to document'
    })
  },

  insertParagraph: async (args: any) => {
    const { text: rawText, location = 'After', style } = args
    const text = stripMarkdown(rawText)
    return Word.run(async context => {
      // Split on \n so each line becomes its own paragraph
      const lines = normalizeLineBreaks(text).split('\n')
      let paragraph: Word.Paragraph
      if (location === 'Start' || location === 'End') {
        const body = context.document.body
        paragraph = body.insertParagraph(lines[0], location)
      } else {
        // Anchor to the whole paragraph the cursor sits in, never to the raw
        // selection — see getBlockAnchor for why a partial range splits it.
        const anchor = await getBlockAnchor(context, context.document.getSelection(), location)
        paragraph = anchor.insertParagraph(lines[0], location as 'After' | 'Before')
      }
      if (style) {
        paragraph.styleBuiltIn = style as Word.BuiltInStyleName
      }
      const inserted: Word.Paragraph[] = [paragraph]
      for (let i = 1; i < lines.length; i++) {
        const nextPara = paragraph.insertParagraph(lines[i], 'After')
        if (style) {
          nextPara.styleBuiltIn = style as Word.BuiltInStyleName
        }
        paragraph = nextPara
        inserted.push(nextPara)
      }

      await detachFromInheritedList(context, inserted)

      // Move cursor to end of last inserted paragraph so consecutive calls
      // insert in correct top-to-bottom order instead of reversing
      paragraph.getRange('End').select()
      await context.sync()
      return `Successfully inserted paragraph at ${location}`
    })
  },

  formatText: async (args: any) => {
    const { bold, italic, underline, fontSize, fontName, fontColor, highlightColor } = args
    return Word.run(async context => {
      const range = context.document.getSelection()

      if (bold !== undefined) range.font.bold = bold
      if (italic !== undefined) range.font.italic = italic
      if (underline !== undefined) range.font.underline = underline
      if (fontSize !== undefined) range.font.size = fontSize
      if (fontName !== undefined) range.font.name = fontName
      if (fontColor !== undefined) range.font.color = fontColor
      if (highlightColor !== undefined) range.font.highlightColor = highlightColor

      await context.sync()
      return 'Successfully applied formatting'
    })
  },

  searchAndReplace: async (args: any) => {
    const { searchText: rawSearch, replaceText: rawReplace, matchCase = false, keepStyle = false } = args
    const searchText = prepareSearchText(rawSearch)
    const replaceText = stripMarkdown(rawReplace)
    return Word.run(async context => {
      const { body, parsed } = await getDocumentParsed(context)
      const cleanPositions = matchCase
        ? countOccurrences(parsed.cleanText, searchText)
        : countOccurrences(parsed.cleanText.toLowerCase(), searchText.toLowerCase())
      const ranges = await resolveAllOccurrencesCaseAware(context, body, parsed, searchText, matchCase)

      if (ranges.length === 0) {
        if (cleanPositions === 0) {
          return `No occurrences of "${searchText}" found in document`
        }
        throw new Error(
          `Found ${cleanPositions} match(es) in document text but Word could not resolve ` +
          `any to a replaceable range. Try a more specific or shorter phrase, or use ` +
          `find_and_select_text + replace_selected_text for content inside table cells.`,
        )
      }

      // Replace right-to-left to preserve earlier range positions
      for (let i = ranges.length - 1; i >= 0; i--) {
        await trackedReplace(context, ranges[i], replaceText, keepStyle)
      }

      const unresolved = cleanPositions - ranges.length
      const suffix =
        unresolved > 0
          ? ` (${unresolved} match(es) could not be resolved and were left unchanged — ` +
            `try a shorter, more unique phrase)`
          : ''
      return `Replaced ${ranges.length} occurrence(s) of "${searchText}" with "${replaceText}"${suffix}`
    })
  },

  searchAndReplaceInSelection: async (args: any) => {
    const { searchText: rawSearch, replaceText: rawReplace, matchCase = false, keepStyle = false } = args
    const searchText = prepareSearchText(rawSearch)
    const replaceText = stripMarkdown(rawReplace)
    return Word.run(async context => {
      const selection = context.document.getSelection()
        selection.load('text')
        await context.sync()

        if (!selection.text || selection.text.length === 0) {
          throw new Error('Nothing is selected.')
        }

        // Fast path: try direct search within selection
        const simpleResults = selection.search(searchText, {
          matchCase: true,
          matchWildcards: false,
        })
        simpleResults.load('items')
        await context.sync()

        if (simpleResults.items.length > 0) {
          console.log(`  [WordTools] Simple search: ${simpleResults.items.length} match(es) in selection`)
          for (let i = simpleResults.items.length - 1; i >= 0; i--) {
            await trackedReplace(context, simpleResults.items[i], replaceText, keepStyle)
          }
          return `Replaced ${simpleResults.items.length} occurrence(s) of "${searchText}" in the selection with "${replaceText}"`
        }

        // Fallback: full OOXML resolution, filter to selection
        console.log('  [WordTools] Simple search failed, using OOXML fallback…')
        const { body, parsed } = await getDocumentParsed(context)
        const allRanges = await resolveAllOccurrencesCaseAware(context, body, parsed, searchText, matchCase)

        if (allRanges.length === 0) {
          return `No occurrences of "${searchText}" found in document`
        }

        // Filter: keep only ranges inside the selection
        const cmps = allRanges.map(r => selection.compareLocationWith(r))
        await context.sync()

        const inSelection: Word.Range[] = []
        for (let i = 0; i < allRanges.length; i++) {
          if (cmps[i].value === 'Contains' || cmps[i].value === 'Equal') {
            inSelection.push(allRanges[i])
          }
        }

        if (inSelection.length === 0) {
          return `No occurrences of "${searchText}" found within current selection`
        }

        // Replace right-to-left
        for (let i = inSelection.length - 1; i >= 0; i--) {
          await trackedReplace(context, inSelection[i], replaceText, keepStyle)
        }

        return `Replaced ${inSelection.length} occurrence(s) of "${searchText}" in the selection with "${replaceText}"`
      })
  },

  getDocumentProperties: async () => {
    return Word.run(async context => {
      const { parsed } = await getDocumentParsed(context)
      const displayText = toDisplayText(parsed)

      const paragraphs = context.document.body.paragraphs
      paragraphs.load('items')
      await context.sync()

      const wordCount = displayText.split(/\s+/).filter(word => word.length > 0).length
      const charCount = parsed.cleanText.length
      const paragraphCount = paragraphs.items.length

      return JSON.stringify(
        {
          paragraphCount,
          wordCount,
          characterCount: charCount,
        },
        null,
        2,
      )
    })
  },

  insertTable: async (args: any) => {
      const { rows, columns, data } = args
      return Word.run(async context => {
        // A table is block content: anchoring it to a partial selection makes
        // Word split the host paragraph around it. See getBlockAnchor.
        const anchor = await getBlockAnchor(context, context.document.getSelection(), 'After')

        // Create table data
        const tableData: string[][] =
          data ||
          Array(rows)
            .fill(null)
            .map(() => Array(columns).fill(''))

        const table = anchor.insertTable(rows, columns, 'After', tableData)
        table.styleBuiltIn = 'GridTable1Light'
        // Advance cursor past the table for correct ordering.
        // Must be 'After', not 'End': for a table 'End' is the point *before* the
        // end-of-table marker, i.e. still inside the last cell. Leaving the cursor
        // there breaks any following operation Word forbids inside a table — most
        // visibly insertPageBreak, which fails with GeneralException.
        table.getRange('After').select()

        await context.sync()
        return `Successfully inserted ${rows}x${columns} table`
      })
  },

  insertList: async (args: any) => {
    const { items, listType } = args
      if (!Array.isArray(items) || items.length === 0) {
        throw new Error('insertList: "items" must be a non-empty array of strings.')
      }
      return Word.run(async context => {
        // A list is block content: anchoring it to a partial selection makes
        // Word split the host paragraph around it. See getBlockAnchor.
        const anchor = await getBlockAnchor(context, context.document.getSelection(), 'After')
        const firstParagraph = anchor.insertParagraph(items[0], 'After')

        // Word carries list membership onto a paragraph inserted adjacent to an
        // existing list, and startNewList() throws GeneralException on a paragraph
        // that is already a list item. Detaching first is what makes a list inserted
        // directly after another list work — without it, the second list always
        // fails and strands its first item as an orphan in the preceding list.
        firstParagraph.load('isListItem')
        await context.sync()
        if (firstParagraph.isListItem) {
          firstParagraph.detachFromList()
          await context.sync()
        }

        // detachFromList() drops list membership but leaves behind the indentation
        // the old list applied, and a list level's indent IS the paragraph indent
        // (see setLevelIndents docs) — so the new list's indent stacks on top of the
        // inherited one and every list inserted after another renders one level
        // deeper, as a sub-list of its predecessor. Reset to a known baseline.
        firstParagraph.leftIndent = 0
        firstParagraph.firstLineIndent = 0
        await context.sync()

        const list = firstParagraph.startNewList()
        list.load('$none')
        await context.sync()

        for (let i = 1; i < items.length; i++) {
          list.insertParagraph(items[i], 'End')
        }

        if (listType === 'bullet') {
          list.setLevelBullet(0, Word.ListBullet.solid)
        } else {
          // The format string is what Word renders per item; the level number (0)
          // is substituted for the integer entry, giving "1." / "2." / "3.".
          list.setLevelNumbering(0, Word.ListNumbering.arabic, [0, '.'])
        }

        // Pin level 0 to Word's default top-level list geometry: 0.25" (18pt) text
        // indent with a matching hanging indent, so the bullet/number sits at the
        // margin. This is the list-level counterpart to the paragraph reset above —
        // together they make the list's depth explicit instead of inherited.
        list.setLevelIndents(0, 18, -18)

        // Advance cursor past the list for correct ordering
        const listParagraphs = list.paragraphs
        listParagraphs.load('items')
        await context.sync()
        if (listParagraphs.items.length > 0) {
          listParagraphs.items[listParagraphs.items.length - 1].getRange('End').select()
        }

        await context.sync()
        return `Successfully inserted ${listType} list with ${items.length} items`
      })
  },

  deleteText: async () => {
    return Word.run(async context => {
      const range = context.document.getSelection()
      range.load('text')
      await context.sync()

      const len = (range.text ?? '').length
      if (len === 0) {
        throw new Error(
          'deleteText: nothing is selected. Select text first with findAndSelectText or selectBetweenText.',
        )
      }
      range.delete()
      await context.sync()
      return `Successfully deleted ${len} characters`
    })
  },

  clearFormatting: async () => {
    return Word.run(async context => {
      const range = context.document.getSelection()
      range.styleBuiltIn = 'Normal'
      range.font.bold = false
      range.font.italic = false
      range.font.underline = 'None'
      range.font.strikeThrough = false
      range.font.subscript = false
      range.font.superscript = false
      // office-js types `highlightColor` as `string`, but the Office.js docs for this
      // property state that setting it to `null` removes the highlight — the .d.ts is
      // simply missing `| null`. Narrow assertion to bypass that typing gap only.
      range.font.highlightColor = null as unknown as string
      await context.sync()
      return 'Successfully cleared formatting'
    })
  },

  insertPageBreak: async (args: any) => {
    const { location = 'After' } = args
      return Word.run(async context => {
        // A page break is block content — anchor it to the whole paragraph the
        // cursor is in, never to a partial selection. See getBlockAnchor.
        const host = await getBlockAnchor(context, context.document.getSelection(), location)

        // insertBreak only supports Before and After for page breaks
        if (location === 'Start' || location === 'Before') {
          // The break lands before the cursor, so the cursor is already past it.
          host.insertBreak('Page', 'Before')
          await context.sync()
          return `Successfully inserted page break ${location.toLowerCase()}`
        }

        // insertBreak returns void, so there is no handle on the break to move
        // the cursor beyond it. Anchoring the break to a new paragraph gives
        // one. Without this the cursor stays *before* the break and everything
        // inserted afterwards is pushed in ahead of it, so the break slides down
        // the document and ends up trailing at the very end.
        const carrier = host.insertParagraph('', 'After')
        await detachFromInheritedList(context, [carrier])
        carrier.insertBreak('Page', 'Before')
        carrier.getRange('Start').select()
        await context.sync()
        return `Successfully inserted page break ${location.toLowerCase()}`
      })
  },

  getRangeInfo: async () => {
    return Word.run(async context => {
      const range = context.document.getSelection()
      range.load(['text', 'style', 'font/name', 'font/size', 'font/bold', 'font/italic', 'font/underline', 'font/color'])
      await context.sync()

      // getOoxml() throws GeneralException on a collapsed selection — only ask for
      // it once we know there is something selected. Formatting is still reported
      // either way, since it describes the cursor position when nothing is selected.
      const hasSelection = (range.text ?? '').length > 0
      let text = ''
      if (hasSelection) {
        const ooxmlResult = range.getOoxml()
        await context.sync()
        text = sanitizeWordText(toDisplayText(parseOoxml(ooxmlResult.value)))
      }

      return JSON.stringify(
        {
          hasSelection,
          text,
          style: range.style,
          font: {
            name: range.font.name,
            size: range.font.size,
            bold: range.font.bold,
            italic: range.font.italic,
            underline: range.font.underline,
            color: range.font.color,
          },
        },
        null,
        2,
      )
    })
  },

  selectText: async (args: any) => {
    const { scope } = args
    return Word.run(async context => {
      if (scope === 'All') {
        const body = context.document.body
        body.select()
        await context.sync()
        return 'Successfully selected all text'
      }
      throw new Error(`selectText: unsupported scope "${scope}"`)
    })
  },

  insertImage: async (args: any) => {
    const { imageUrl, width, height, location = 'After' } = args

    let base64: string
    let note = ''
    if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
      const fetched = await fetchImageAsBase64(imageUrl)
      base64 = fetched.base64
      if (fetched.converted) note = ` (converted from ${fetched.sourceContentType} to PNG)`
    } else {
      // Already base64 — strip data URI prefix if present
      base64 = imageUrl.includes(',') ? imageUrl.split(',')[1] : imageUrl
    }

    return Word.run(async context => {
      let image: Word.InlinePicture
      if (location === 'Before' || location === 'After') {
        // Give the picture its own paragraph. Word only inserts inline
        // pictures at Replace/Start/End of a range, so "before/after the
        // cursor" has to mean a new paragraph next to the current one —
        // otherwise the image is jammed into the middle of existing text.
        const anchor = await getBlockAnchor(context, context.document.getSelection(), location)
        const holder = anchor.insertParagraph('', location as 'Before' | 'After')
        await detachFromInheritedList(context, [holder])
        image = holder.insertInlinePictureFromBase64(base64, 'End')
        holder.getRange('End').select()
      } else {
        const range = context.document.getSelection()
        image = range.insertInlinePictureFromBase64(
          base64,
          location as Word.InsertLocation.replace | Word.InsertLocation.start | Word.InsertLocation.end,
        )
      }

      if (width) image.width = width
      if (height) image.height = height

      await context.sync()
      return `Successfully inserted image at ${location}${note}`
    })
  },

  getTableInfo: async () => {
    return Word.run(async context => {
        const tables = context.document.body.tables
        tables.load(['items'])
        await context.sync()

        const tableInfos = []
        for (let i = 0; i < tables.items.length; i++) {
          const table = tables.items[i]
          table.load(['rowCount', 'values'])
          await context.sync()

          const columnCount = table.values && table.values[0] ? table.values[0].length : 0

          tableInfos.push({
            index: i,
            rowCount: table.rowCount,
            columnCount,
          })
        }

        return JSON.stringify(
          {
            tableCount: tables.items.length,
            tables: tableInfos,
          },
          null,
          2,
        )
      })
  },

  insertBookmark: async (args: any) => {
    const { name } = args
    return Word.run(async context => {
      const range = context.document.getSelection()
      range.load('text')
      await context.sync()
      if ((range.text ?? '').length === 0) {
        throw new Error(
          'insertBookmark: nothing is selected. A bookmark must wrap existing text — ' +
            'select it first with findAndSelectText or selectBetweenText.',
        )
      }

      const bookmarkName = name.replace(/\s+/g, '_')

      const contentControl = range.insertContentControl()
      contentControl.tag = `bookmark_${bookmarkName}`
      contentControl.title = bookmarkName
      contentControl.appearance = 'Tags'

      // Park the cursor outside the control. A content control grows to swallow
      // anything inserted while the cursor is inside it, so leaving it there
      // makes the very next insert become part of the bookmark instead of
      // following it.
      contentControl.getRange('After').select()
      await context.sync()
      return `Successfully inserted bookmark: ${bookmarkName}`
    })
  },

  goToBookmark: async (args: any) => {
    const { name } = args
    return Word.run(async context => {
      const bookmarkName = name.replace(/\s+/g, '_')
      const contentControls = context.document.contentControls
      contentControls.load('items/tag,items/title')
      await context.sync()

      for (const cc of contentControls.items) {
        if (cc.tag === `bookmark_${bookmarkName}` || cc.title === bookmarkName) {
          // Select the content, not the control itself: a whole-control
          // selection includes the container, so replacing or formatting it
          // would act on the bookmark rather than the text it marks.
          cc.getRange('Content').select()
          await context.sync()
          return `Successfully navigated to bookmark: ${bookmarkName}`
        }
      }

      const known = contentControls.items
        .filter(cc => cc.tag?.startsWith('bookmark_'))
        .map(cc => cc.tag.slice('bookmark_'.length))
      return known.length > 0
        ? `Bookmark not found: ${bookmarkName}. Existing bookmarks: ${known.join(', ')}`
        : `Bookmark not found: ${bookmarkName}. The document has no bookmarks.`
    })
  },

  insertContentControl: async (args: any) => {
    const { title, tag, appearance = 'BoundingBox' } = args
    return Word.run(async context => {
      const range = context.document.getSelection()
      range.load('text')
      await context.sync()
      if ((range.text ?? '').length === 0) {
        throw new Error(
          'insertContentControl: nothing is selected. A content control must wrap existing ' +
            'content — select it first with findAndSelectText or selectBetweenText.',
        )
      }

      const selectedText = sanitizeWordText(range.text).trim()

      const contentControl = range.insertContentControl()
      contentControl.title = title
      if (tag) contentControl.tag = tag
      contentControl.appearance = appearance as Word.ContentControlAppearance
      contentControl.load('text')
      await context.sync()

      // Word does not always wrap the range it was given — notably when the
      // selection already sits inside another content control. It then leaves
      // an *empty* control behind, which shows up in the document as the
      // "Click or tap here to enter text." placeholder. Reporting success for
      // that would hide real document corruption, so check what was captured.
      if (sanitizeWordText(contentControl.text ?? '').trim().length === 0 && selectedText.length > 0) {
        // Remove the stray control rather than leaving the placeholder behind
        // as document content the next reader would mistake for real text.
        contentControl.delete(false)
        await context.sync()
        throw new Error(
          `insertContentControl: Word created an empty content control instead of wrapping ` +
            `"${selectedText.slice(0, 60)}", so it was removed again. This happens when the ` +
            `selection is already inside another content control or bookmark — Word cannot nest ` +
            `them here. Select text that is not already bookmarked and try again.`,
        )
      }

      // See insertBookmark: a content control absorbs anything inserted while
      // the cursor is inside it, so move the cursor past it.
      contentControl.getRange('After').select()
      await context.sync()
      return `Successfully inserted content control: ${title}`
    })
  },

  findText: async (args: any) => {
    const { searchText: rawSearch, matchCase = false } = args
      const searchText = prepareSearchText(rawSearch)
      return Word.run(async context => {
        const { parsed } = await getDocumentParsed(context)
        const { cleanText, boundaries, hardBreaks } = parsed
        const CTX = 30
        const target = matchCase ? searchText : searchText.toLowerCase()
        const haystack = matchCase ? cleanText : cleanText.toLowerCase()
        const matches: FindMatch[] = []

        let pos = 0
        while (true) {
          const idx = haystack.indexOf(target, pos)
          if (idx === -1) break
          const end = idx + searchText.length - 1
          let hasBoundaries = false
          for (let i = idx + 1; i <= end; i++) {
            if (boundaries[i]) {
              hasBoundaries = true
              break
            }
          }
          matches.push({
            index: idx,
            contextBefore: sliceToDisplay(cleanText, hardBreaks, Math.max(0, idx - CTX), idx),
            contextAfter: sliceToDisplay(cleanText, hardBreaks, end + 1, Math.min(cleanText.length, end + 1 + CTX)),
            hasBoundaries,
          })
          pos = idx + 1
        }

        // Quick check: can body.search resolve these matches?
        // This tells the LLM upfront whether search_and_replace will succeed.
        let resolvable = false
        if (matches.length > 0) {
          try {
            const body = context.document.body
            const probe = body.search(searchText, { matchCase, matchWildcards: false })
            probe.load('items')
            await context.sync()
            resolvable = probe.items.length > 0
          } catch {
            resolvable = false
          }
        }

        return JSON.stringify(
          {
            searchText,
            matchCount: matches.length,
            found: matches.length > 0,
            resolvable,
            matches,
          },
          null,
          2,
        )
      })
  },

  findAndSelectText: async (args: any) => {
    const { searchText: rawSearch, matchCase = false } = args
    const searchText = prepareSearchText(rawSearch)
    return Word.run(async context => {
      const { body, parsed } = await getDocumentParsed(context)
      const target = matchCase ? searchText : searchText.toLowerCase()
        const haystack = matchCase ? parsed.cleanText : parsed.cleanText.toLowerCase()

        if (haystack.indexOf(target) === -1) {
          return JSON.stringify(
            {
              success: false,
              message: `No matches found for "${searchText}"`,
              matchCount: 0,
            },
            null,
            2,
          )
        }

        const ranges = await resolveAllOccurrencesCaseAware(context, body, parsed, searchText, matchCase)
        if (ranges.length === 0) {
          return JSON.stringify(
            {
              success: false,
              message: `Text found in clean content but could not resolve to document range: "${searchText}"`,
              matchCount: 0,
            },
            null,
            2,
          )
        }

        ranges[0].select()
        await context.sync()

        return JSON.stringify(
          {
            success: true,
            message: `Selected first occurrence of "${searchText}" (found ${ranges.length} total matches)`,
            matchCount: ranges.length,
            selectedIndex: 0,
          },
          null,
          2,
        )
      })
  },

  selectBetweenText: async (args: any) => {
      const { startText: rawStart, endText: rawEnd, matchCase = false } = args
      const startText = prepareSearchText(rawStart, 'startText')
      const endText = prepareSearchText(rawEnd, 'endText')
      return Word.run(async context => {
        const { body, parsed } = await getDocumentParsed(context)
        const { cleanText } = parsed

        const haystack = matchCase ? cleanText : cleanText.toLowerCase()
        const startNeedle = matchCase ? startText : startText.toLowerCase()
        const endNeedle = matchCase ? endText : endText.toLowerCase()

        // Uniqueness validation on clean text
        const startCount = countOccurrences(haystack, startNeedle)
        if (startCount === 0) {
          return JSON.stringify({ success: false, message: `Start marker "${startText}" not found` }, null, 2)
        }
        if (startCount > 1) {
          return JSON.stringify(
            {
              success: false,
              message: `Anchors are not unique. Found ${startCount} start anchor(s). Please use unique text markers.`,
              startCount,
              endCount: countOccurrences(haystack, endNeedle),
            },
            null,
            2,
          )
        }

        const endCount = countOccurrences(haystack, endNeedle)
        if (endCount === 0) {
          return JSON.stringify({ success: false, message: `End marker "${endText}" not found` }, null, 2)
        }
        if (endCount > 1) {
          return JSON.stringify(
            {
              success: false,
              message: `Anchors are not unique. Found ${endCount} end anchor(s). Please use unique text markers.`,
              startCount,
              endCount,
            },
            null,
            2,
          )
        }

        const startIdx = haystack.indexOf(startNeedle)
        const endIdx = haystack.indexOf(endNeedle)
        if (endIdx < startIdx + startText.length) {
          return JSON.stringify(
            {
              success: false,
              message: `End marker "${endText}" does not come after start marker "${startText}". Selection would be empty or backwards.`,
            },
            null,
            2,
          )
        }

        // Extract actual-cased text from cleanText for resolution
        const actualStart = cleanText.slice(startIdx, startIdx + startText.length)
        const actualEnd = cleanText.slice(endIdx, endIdx + endText.length)

        const startResult = await resolveCleanTextToRange(context, body, parsed, actualStart)
        if (!startResult) {
          return JSON.stringify(
            { success: false, message: 'Failed to resolve start marker to document range.' },
            null,
            2,
          )
        }

        const endResult = await resolveCleanTextToRange(context, body, parsed, actualEnd)
        if (!endResult) {
          return JSON.stringify({ success: false, message: 'Failed to resolve end marker to document range.' }, null, 2)
        }

        // Select range including both markers (Start of start marker → End of end marker)
        const selectionStart = startResult.range.getRange('Start')
        const selectionEnd = endResult.range.getRange('End')
        const selectionRange = selectionStart.expandTo(selectionEnd)
        selectionRange.select()
        selectionRange.load('text')
        await context.sync()

        return JSON.stringify(
          {
            success: true,
            message: `Selected range from "${startText}" to "${endText}"`,
            selectedCharCount: (selectionRange.text ?? '').length,
          },
          null,
          2,
        )
      })
  },

  setParagraphFormat: async (args: any) => {
    const { alignment, lineSpacing, spaceBefore, spaceAfter, firstLineIndent, leftIndent, rightIndent } = args
      return Word.run(async context => {
        const range = context.document.getSelection()
        const paragraphs = range.paragraphs
        paragraphs.load('items')
        await context.sync()

        for (const para of paragraphs.items) {
          if (alignment !== undefined) para.alignment = alignment as Word.Alignment
          if (lineSpacing !== undefined) para.lineSpacing = lineSpacing
          if (spaceBefore !== undefined) para.spaceBefore = spaceBefore
          if (spaceAfter !== undefined) para.spaceAfter = spaceAfter
          if (firstLineIndent !== undefined) para.firstLineIndent = firstLineIndent
          if (leftIndent !== undefined) para.leftIndent = leftIndent
          if (rightIndent !== undefined) para.rightIndent = rightIndent
        }

        await context.sync()
        return `Successfully applied paragraph formatting to ${paragraphs.items.length} paragraph(s)`
      })
  },

  setStyle: async (args: any) => {
    const { style } = args
    return Word.run(async context => {
      const range = context.document.getSelection()
      range.styleBuiltIn = style as Word.BuiltInStyleName
      await context.sync()
      return `Successfully applied style: ${style}`
    })
  },

  insertComment: async (args: any) => {
    const { comment } = args
    return Word.run(async context => {
      const range = context.document.getSelection()
      range.load('text')
      await context.sync()
      if (!range.text.trim()) throw new Error('No text is selected. Select text first before adding a comment.')
      const commentObj = range.insertComment(comment)
      commentObj.load('authorName')
      await context.sync()
      return `Comment added by ${commentObj.authorName}: "${comment}"`
    })
  },
}

export type WordToolName = keyof typeof wordToolExecutors

export function getWordTool(name: string) {
  const fn = wordToolExecutors[name as WordToolName]
  if (!fn) throw new Error(`getWordTool: no local executor for Word tool "${name}"`)
  return fn
}

/**
 * Read the current Word selection as clean text (tracked-change deletions stripped).
 * Use this instead of `range.text` anywhere selection text is passed to the LLM.
 */
export async function getCleanSelectedText(): Promise<string> {
  return Word.run(async context => {
    const sel = context.document.getSelection()
    // See getSelectedText: getOoxml() throws on a collapsed selection.
    sel.load('text')
    await context.sync()
    if ((sel.text ?? '').length === 0) return ''

    const ooxmlResult = sel.getOoxml()
    await context.sync()
    return sanitizeWordText(toDisplayText(parseOoxml(ooxmlResult.value)))
  })
}
