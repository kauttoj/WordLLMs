import { tool } from '@langchain/core/tools'
import { z } from 'zod'

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

/**
 * Insert text into a Word range, splitting on \n to create proper paragraphs.
 * Office.js insertText handles \n inconsistently across platforms, so we
 * explicitly use insertParagraph for each line (proven pattern from common.ts).
 */
/**
 * Insert text into a Word range, splitting on \n to create proper paragraphs.
 * Returns the last inserted paragraph (for multi-line) so callers can
 * move the cursor to maintain correct ordering across tool calls.
 */
function insertTextSafe(
  range: Word.Range,
  text: string,
  location: Word.InsertLocation,
): Word.Paragraph | null {
  const lines = text.replace(/\r\n|\r/g, '\n').split('\n')
  if (lines.length === 1) {
    range.insertText(text, location)
    return null
  }
  range.insertText(lines[0], location)
  let lastPara: Word.Paragraph | null = null
  for (let i = 1; i < lines.length; i++) {
    lastPara = range.insertParagraph(lines[i], 'After')
    lastPara.styleBuiltIn = 'Normal'
  }
  return lastPara
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
  boundaries: boolean[]
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
  let pendingBreak = false
  let inFieldInstruction = false
  let fieldDepth = 0

  function addChar(ch: string) {
    boundaries.push(pendingBreak && cleanText.length > 0)
    pendingBreak = false
    cleanText += ch
  }

  function walk(el: Element) {
    for (const child of Array.from(el.childNodes)) {
      if (child.nodeType !== 1) continue
      const ln = (child as Element).localName

      if (ln === 'del' || ln === 'comment') {
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
        if (cleanText.length > 0) pendingBreak = true
        walk(child as Element)
        continue
      }

      // Explicit line break (Shift+Enter)
      if (ln === 'br') {
        if (cleanText.length > 0) pendingBreak = true
        continue
      }

      // Tab character (would otherwise be silently dropped)
      if (ln === 'tab') {
        addChar('\t')
        continue
      }

      walk(child as Element)
    }
  }

  walk(xmlDoc.documentElement)
  return { cleanText, boundaries }
}

/** Convert cleanText + boundaries into display text with \n at paragraph boundaries. */
function toDisplayText(parsed: ParsedDocument): string {
  const { cleanText, boundaries } = parsed
  let result = ''
  for (let i = 0; i < cleanText.length; i++) {
    if (boundaries[i]) result += '\n'
    result += cleanText[i]
  }
  return result
}

/** Convert a cleanText slice [from, to) into display text with \n at boundaries. */
function sliceToDisplay(cleanText: string, boundaries: boolean[], from: number, to: number): string {
  let result = ''
  for (let i = from; i < to && i < cleanText.length; i++) {
    if (boundaries[i]) result += '\n'
    result += cleanText[i]
  }
  return result
}

/** Strip \n from search queries — LLM sees \n in text but cleanText has none. */
function stripNewlines(s: string): string {
  return s.replace(/\n/g, '')
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

async function searchBody(
  context: Word.RequestContext,
  body: Word.Body,
  text: string,
  label: string,
): Promise<Word.Range[] | null> {
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
}

async function searchWithinRange(
  context: Word.RequestContext,
  range: Word.Range,
  text: string,
  label: string,
): Promise<Word.Range[] | null> {
  const r = range.search(text, { matchCase: true, matchWildcards: false })
  r.load('items')
  await context.sync()
  if (r.items.length > 0) return r.items
  console.error(`  [WordTools] ${label}: NOT FOUND within range`)
  return null
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

  // Resolve single-segment: one body.search() call
  const resolved: { positionIndex: number; range: Word.Range }[] = []

  if (singleOccs.length > 0) {
    const items = await searchBody(context, body, searchText, 'single-seg-all')
    if (items) {
      if (items.length < singleOccs.length) {
        console.warn(
          `  [WordTools] body.search returned ${items.length} but expected ${singleOccs.length}. Using available matches.`,
        )
      }
      const count = Math.min(items.length, singleOccs.length)
      for (let i = 0; i < count; i++) {
        resolved.push({ positionIndex: singleOccs[i].positionIndex, range: items[i] })
      }
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

async function trackedReplace(context: Word.RequestContext, range: Word.Range, newText: string): Promise<void> {
  context.document.load('changeTrackingMode')
  await context.sync()
  const saved = context.document.changeTrackingMode
  context.document.changeTrackingMode = Word.ChangeTrackingMode.trackAll
  range.insertText(newText, Word.InsertLocation.replace)
  await context.sync()
  context.document.changeTrackingMode = saved
  // Reset style on non-first paragraphs to prevent heading style bleeding
  if (newText.includes('\n')) {
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

export type WordToolName =
  | 'getSelectedText'
  | 'getDocumentContent'
  | 'insertText'
  | 'replaceSelectedText'
  | 'appendText'
  | 'insertParagraph'
  | 'formatText'
  | 'searchAndReplace'
  | 'searchAndReplaceInSelection'
  | 'getDocumentProperties'
  | 'insertTable'
  | 'insertList'
  | 'deleteText'
  | 'clearFormatting'
  | 'insertPageBreak'
  | 'getRangeInfo'
  | 'selectText'
  | 'insertImage'
  | 'getTableInfo'
  | 'insertBookmark'
  | 'goToBookmark'
  | 'insertContentControl'
  | 'findText'
  | 'findAndSelectText'
  | 'selectBetweenText'
  | 'setParagraphFormat'
  | 'setStyle'
  | 'insertComment'

/** Word tools that only read document content without modifying it. */
export const READ_ONLY_WORD_TOOLS: WordToolName[] = [
  'getSelectedText',
  'getDocumentContent',
  'getDocumentProperties',
  'getRangeInfo',
  'getTableInfo',
  'findText',
  'selectText',
  'findAndSelectText',
  'selectBetweenText',
  'goToBookmark',
]

const wordToolDefinitions: Record<WordToolName, WordToolDefinition> = {
  getSelectedText: {
    name: 'getSelectedText',
    description:
      'Get the currently selected text in the Word document. Paragraph breaks appear as newlines. Returns the selected text or empty string if nothing is selected.',
    inputSchema: {
      type: 'object',
      properties: {},
      required: [],
    },
    execute: async () => {
      return Word.run(async context => {
        const sel = context.document.getSelection()
        const ooxmlResult = sel.getOoxml()
        await context.sync()
        const parsed = parseOoxml(ooxmlResult.value)
        return sanitizeWordText(toDisplayText(parsed))
      })
    },
  },

  getDocumentContent: {
    name: 'getDocumentContent',
    description: 'Get the full content of the Word document body as plain text. Paragraph breaks appear as newlines.',
    inputSchema: {
      type: 'object',
      properties: {},
      required: [],
    },
    execute: async () => {
      return Word.run(async context => {
        const { parsed } = await getDocumentParsed(context)
        return sanitizeWordText(toDisplayText(parsed))
      })
    },
  },

  insertText: {
    name: 'insertText',
    description:
      'Insert plain text at the current cursor position. Do not use markdown. Use \\n for paragraph breaks. The cursor advances after each insertion.',
    inputSchema: {
      type: 'object',
      properties: {
        text: {
          type: 'string',
          description: 'The text to insert. Use \\n for paragraph breaks.',
        },
        location: {
          type: 'string',
          description: 'Where to insert relative to cursor: "Start", "End", "Before", "After", or "Replace"',
          enum: ['Start', 'End', 'Before', 'After', 'Replace'],
        },
      },
      required: ['text'],
    },
    execute: async args => {
      const { text: rawText, location = 'End' } = args
      const text = stripMarkdown(rawText)
      return Word.run(async context => {
        const range = context.document.getSelection()
        const lastPara = insertTextSafe(range, text, location as Word.InsertLocation)
        // Move cursor to end of inserted content so consecutive calls
        // insert in correct order instead of reversing
        if (lastPara) {
          lastPara.getRange('End').select()
        }
        await context.sync()
        return `Successfully inserted text at ${location}`
      })
    },
  },

  replaceSelectedText: {
    name: 'replaceSelectedText',
    description:
      'Replace the entire selection with new content. For small targeted edits, use searchAndReplace instead. Do not use markdown. Use \\n for paragraph breaks.',
    inputSchema: {
      type: 'object',
      properties: {
        newText: {
          type: 'string',
          description: 'The replacement text. Use \\n for paragraph breaks.',
        },
      },
      required: ['newText'],
    },
    execute: async args => {
      const { newText: rawNewText } = args
      const newText = stripMarkdown(rawNewText)
      return Word.run(async context => {
        const selection = context.document.getSelection()
        selection.load('text')
        await context.sync()

        if (!selection.text || selection.text.length === 0) {
          throw new Error('Nothing is selected.')
        }

        await trackedReplace(context, selection, newText)
        return 'Successfully replaced selected text'
      })
    },
  },

  appendText: {
    name: 'appendText',
    description:
      'Append plain text to the end of the document. Do not use markdown. Use \\n for paragraph breaks.',
    inputSchema: {
      type: 'object',
      properties: {
        text: {
          type: 'string',
          description: 'The text to append. Use \\n for paragraph breaks.',
        },
      },
      required: ['text'],
    },
    execute: async args => {
      const { text: rawText } = args
      const text = stripMarkdown(rawText)
      return Word.run(async context => {
        const body = context.document.body
        const range = body.getRange('End')
        insertTextSafe(range, text, 'End')
        await context.sync()
        return 'Successfully appended text to document'
      })
    },
  },

  insertParagraph: {
    name: 'insertParagraph',
    description:
      'Insert a new paragraph. Use the style parameter for headings, quotes, etc. Do not use markdown. The cursor advances after insertion, so consecutive calls produce correct top-to-bottom order.',
    inputSchema: {
      type: 'object',
      properties: {
        text: {
          type: 'string',
          description: 'The paragraph text.',
        },
        location: {
          type: 'string',
          description:
            '"After" (default, after cursor), "Before", "Start" (start of doc), or "End" (end of doc).',
          enum: ['After', 'Before', 'Start', 'End'],
        },
        style: {
          type: 'string',
          description: 'Optional Word built-in style: Normal, Heading1, Heading2, Heading3, Quote, etc.',
          enum: [
            'Normal',
            'Heading1',
            'Heading2',
            'Heading3',
            'Heading4',
            'Quote',
            'IntenseQuote',
            'Title',
            'Subtitle',
          ],
        },
      },
      required: ['text'],
    },
    execute: async args => {
      const { text: rawText, location = 'After', style } = args
      const text = stripMarkdown(rawText)
      return Word.run(async context => {
        // Split on \n so each line becomes its own paragraph
        const lines = text.replace(/\r\n|\r/g, '\n').split('\n')
        let paragraph: Word.Paragraph
        if (location === 'Start' || location === 'End') {
          const body = context.document.body
          paragraph = body.insertParagraph(lines[0], location)
        } else {
          const range = context.document.getSelection()
          paragraph = range.insertParagraph(lines[0], location as 'After' | 'Before')
        }
        if (style) {
          paragraph.styleBuiltIn = style as Word.BuiltInStyleName
        }
        for (let i = 1; i < lines.length; i++) {
          const nextPara = paragraph.getRange('After').insertParagraph(lines[i], 'After')
          if (style) {
            nextPara.styleBuiltIn = style as Word.BuiltInStyleName
          }
          paragraph = nextPara
        }
        // Move cursor to end of last inserted paragraph so consecutive calls
        // insert in correct top-to-bottom order instead of reversing
        paragraph.getRange('End').select()
        await context.sync()
        return `Successfully inserted paragraph at ${location}`
      })
    },
  },

  formatText: {
    name: 'formatText',
    description: 'Apply formatting to the currently selected text.',
    inputSchema: {
      type: 'object',
      properties: {
        bold: {
          type: 'boolean',
          description: 'Make text bold',
        },
        italic: {
          type: 'boolean',
          description: 'Make text italic',
        },
        underline: {
          type: 'string',
          description: 'Underline style',
          enum: ['None', 'Single', 'Double', 'Dotted', 'Thick', 'Wave'],
        },
        fontSize: {
          type: 'number',
          description: 'Font size in points',
        },
        fontName: {
          type: 'string',
          description: 'Font family name (e.g., "Arial", "Times New Roman", "Calibri", "Consolas")',
        },
        fontColor: {
          type: 'string',
          description: 'Font color as hex (e.g., "#FF0000" for red)',
        },
        highlightColor: {
          type: 'string',
          description: 'Highlight color',
          enum: [
            'Yellow',
            'Green',
            'Cyan',
            'Pink',
            'Blue',
            'Red',
            'DarkBlue',
            'Teal',
            'Lime',
            'Purple',
            'Orange',
            'White',
            'Black',
          ],
        },
      },
      required: [],
    },
    execute: async args => {
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
  },

  searchAndReplace: {
    name: 'searchAndReplace',
    description:
      'Search for text in the document and replace it. Preferred for targeted edits: typos, grammar, proofreading.',
    inputSchema: {
      type: 'object',
      properties: {
        searchText: {
          type: 'string',
          description:
            'The visible text to search for. Newlines are stripped automatically; search works across paragraphs.',
        },
        replaceText: {
          type: 'string',
          description: 'The text to replace with',
        },
        matchCase: {
          type: 'boolean',
          description: 'Whether to match case (default: false)',
        },
      },
      required: ['searchText', 'replaceText'],
    },
    execute: async args => {
      const { searchText: rawSearch, replaceText: rawReplace, matchCase = false } = args
      const searchText = stripNewlines(rawSearch)
      const replaceText = stripMarkdown(rawReplace)
      return Word.run(async context => {
        const { body, parsed } = await getDocumentParsed(context)
        const ranges = await resolveAllOccurrencesCaseAware(context, body, parsed, searchText, matchCase)

        if (ranges.length === 0) {
          return `No occurrences of "${searchText}" found in document`
        }

        // Replace right-to-left to preserve earlier range positions
        for (let i = ranges.length - 1; i >= 0; i--) {
          await trackedReplace(context, ranges[i], replaceText)
        }

        return `Replaced ${ranges.length} occurrence(s) of "${searchText}" with "${replaceText}"`
      })
    },
  },

  searchAndReplaceInSelection: {
    name: 'searchAndReplaceInSelection',
    description: 'Search and replace within the current selection only.',
    inputSchema: {
      type: 'object',
      properties: {
        searchText: {
          type: 'string',
          description:
            'The visible text to search for. Newlines are stripped automatically; search works across paragraphs.',
        },
        replaceText: {
          type: 'string',
          description: 'The text to replace with',
        },
        matchCase: {
          type: 'boolean',
          description: 'Whether to match case (default: false)',
        },
      },
      required: ['searchText', 'replaceText'],
    },
    execute: async args => {
      const { searchText: rawSearch, replaceText: rawReplace, matchCase = false } = args
      const searchText = stripNewlines(rawSearch)
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
            await trackedReplace(context, simpleResults.items[i], replaceText)
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
          await trackedReplace(context, inSelection[i], replaceText)
        }

        return `Replaced ${inSelection.length} occurrence(s) of "${searchText}" in the selection with "${replaceText}"`
      })
    },
  },

  getDocumentProperties: {
    name: 'getDocumentProperties',
    description: 'Get document properties including paragraph count, word count, and character count.',
    inputSchema: {
      type: 'object',
      properties: {},
      required: [],
    },
    execute: async () => {
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
  },

  insertTable: {
    name: 'insertTable',
    description: 'Insert a table at the current cursor position.',
    inputSchema: {
      type: 'object',
      properties: {
        rows: {
          type: 'number',
          description: 'Number of rows',
        },
        columns: {
          type: 'number',
          description: 'Number of columns',
        },
        data: {
          type: 'array',
          description: 'Optional 2D array of cell values',
          items: {
            type: 'array',
            items: { type: 'string' },
          },
        },
      },
      required: ['rows', 'columns'],
    },
    execute: async args => {
      const { rows, columns, data } = args
      return Word.run(async context => {
        const range = context.document.getSelection()

        // Create table data
        const tableData: string[][] =
          data ||
          Array(rows)
            .fill(null)
            .map(() => Array(columns).fill(''))

        const table = range.insertTable(rows, columns, 'After', tableData)
        table.styleBuiltIn = 'GridTable1Light'
        // Advance cursor past the table for correct ordering
        table.getRange('End').select()

        await context.sync()
        return `Successfully inserted ${rows}x${columns} table`
      })
    },
  },

  insertList: {
    name: 'insertList',
    description: 'Insert a bulleted or numbered list at the current position.',
    inputSchema: {
      type: 'object',
      properties: {
        items: {
          type: 'array',
          description: 'Array of list item texts',
          items: { type: 'string' },
        },
        listType: {
          type: 'string',
          description: 'Type of list: "bullet" or "number"',
          enum: ['bullet', 'number'],
        },
      },
      required: ['items', 'listType'],
    },
    execute: async args => {
      const { items, listType } = args
      return Word.run(async context => {
        const range = context.document.getSelection()
        const firstParagraph = range.insertParagraph(items[0], 'After')
        const list = firstParagraph.startNewList()
        list.load('$none')
        await context.sync()

        for (let i = 1; i < items.length; i++) {
          list.insertParagraph(items[i], 'End')
        }

        if (listType === 'bullet') {
          list.setLevelBullet(0, Word.ListBullet.solid)
        } else {
          list.setLevelNumbering(0, Word.ListNumbering.arabic)
        }

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
  },

  deleteText: {
    name: 'deleteText',
    description:
      'Delete the currently selected text or a specific range. If no text is selected, this will delete at the cursor position.',
    inputSchema: {
      type: 'object',
      properties: {
        direction: {
          type: 'string',
          description: 'Direction to delete if nothing selected: "Before" (backspace) or "After" (delete key)',
          enum: ['Before', 'After'],
        },
      },
      required: [],
    },
    execute: async args => {
      const { direction = 'After' } = args
      return Word.run(async context => {
        const range = context.document.getSelection()
        range.load('text')
        await context.sync()

        if (range.text && range.text.length > 0) {
          range.delete()
        } else {
          if (direction === 'After') {
            range.insertText('', 'After')
          } else {
            range.insertText('', 'Before')
          }
        }
        await context.sync()
        return 'Successfully deleted text'
      })
    },
  },

  clearFormatting: {
    name: 'clearFormatting',
    description: 'Clear all formatting from the selected text, returning it to default style.',
    inputSchema: {
      type: 'object',
      properties: {},
      required: [],
    },
    execute: async () => {
      return Word.run(async context => {
        const range = context.document.getSelection()
        range.font.bold = false
        range.font.italic = false
        range.font.underline = 'None'
        range.styleBuiltIn = 'Normal'
        await context.sync()
        return 'Successfully cleared formatting'
      })
    },
  },

  insertPageBreak: {
    name: 'insertPageBreak',
    description: 'Insert a page break at the current cursor position.',
    inputSchema: {
      type: 'object',
      properties: {
        location: {
          type: 'string',
          description: 'Where to insert: "Before", "After", "Start", or "End"',
          enum: ['Before', 'After', 'Start', 'End'],
        },
      },
      required: [],
    },
    execute: async args => {
      const { location = 'After' } = args
      return Word.run(async context => {
        const range = context.document.getSelection()
        // insertBreak only supports Before and After for page breaks
        const insertLoc = location === 'Start' || location === 'Before' ? 'Before' : 'After'
        range.insertBreak('Page', insertLoc)
        await context.sync()
        return `Successfully inserted page break ${location.toLowerCase()}`
      })
    },
  },

  getRangeInfo: {
    name: 'getRangeInfo',
    description:
      'Get detailed information about the current selection including text, formatting, and position. Returns an error if no text is currently selected.',
    inputSchema: {
      type: 'object',
      properties: {},
      required: [],
    },
    execute: async () => {
      return Word.run(async context => {
        const range = context.document.getSelection()
        const ooxmlResult = range.getOoxml()
        range.load(['style', 'font/name', 'font/size', 'font/bold', 'font/italic', 'font/underline', 'font/color'])
        await context.sync()
        const parsed = parseOoxml(ooxmlResult.value)

        return JSON.stringify(
          {
            text: sanitizeWordText(toDisplayText(parsed)),
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
  },

  selectText: {
    name: 'selectText',
    description: 'Select all text in the document or specific location.',
    inputSchema: {
      type: 'object',
      properties: {
        scope: {
          type: 'string',
          description: 'What to select: "All" for entire document',
          enum: ['All'],
        },
      },
      required: ['scope'],
    },
    execute: async args => {
      const { scope } = args
      return Word.run(async context => {
        if (scope === 'All') {
          const body = context.document.body
          body.select()
          await context.sync()
          return 'Successfully selected all text'
        }
        return 'Invalid scope'
      })
    },
  },

  insertImage: {
    name: 'insertImage',
    description:
      'Insert an image at the current cursor position. Accepts an image URL (http/https) or a base64-encoded image string.',
    inputSchema: {
      type: 'object',
      properties: {
        imageUrl: {
          type: 'string',
          description: 'The URL of the image to insert',
        },
        width: {
          type: 'number',
          description: 'Optional width in points',
        },
        height: {
          type: 'number',
          description: 'Optional height in points',
        },
        location: {
          type: 'string',
          description: 'Where to insert: "Before", "After", "Start", "End", or "Replace"',
          enum: ['Before', 'After', 'Start', 'End', 'Replace'],
        },
      },
      required: ['imageUrl'],
    },
    execute: async args => {
      const { imageUrl, width, height, location = 'After' } = args

      let base64: string
      if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
        const response = await fetch(imageUrl)
        if (!response.ok) throw new Error(`Failed to fetch image: ${response.status} ${response.statusText}`)
        const blob = await response.blob()
        base64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onloadend = () => resolve((reader.result as string).split(',')[1])
          reader.onerror = reject
          reader.readAsDataURL(blob)
        })
      } else {
        // Already base64 — strip data URI prefix if present
        base64 = imageUrl.includes(',') ? imageUrl.split(',')[1] : imageUrl
      }

      return Word.run(async context => {
        const range = context.document.getSelection()
        const image = range.insertInlinePictureFromBase64(base64, location as Word.InsertLocation)

        if (width) image.width = width
        if (height) image.height = height

        await context.sync()
        return `Successfully inserted image at ${location}`
      })
    },
  },

  getTableInfo: {
    name: 'getTableInfo',
    description: 'Get information about tables in the document, including row and column counts.',
    inputSchema: {
      type: 'object',
      properties: {},
      required: [],
    },
    execute: async () => {
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
  },

  insertBookmark: {
    name: 'insertBookmark',
    description: 'Insert a bookmark at the current selection to mark a location in the document.',
    inputSchema: {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          description: 'The name of the bookmark (must be unique, no spaces allowed)',
        },
      },
      required: ['name'],
    },
    execute: async args => {
      const { name } = args
      return Word.run(async context => {
        const range = context.document.getSelection()

        const bookmarkName = name.replace(/\s+/g, '_')

        const contentControl = range.insertContentControl()
        contentControl.tag = `bookmark_${bookmarkName}`
        contentControl.title = bookmarkName
        contentControl.appearance = 'Tags'

        await context.sync()
        return `Successfully inserted bookmark: ${bookmarkName}`
      })
    },
  },

  goToBookmark: {
    name: 'goToBookmark',
    description: 'Navigate to a previously created bookmark in the document.',
    inputSchema: {
      type: 'object',
      properties: {
        name: {
          type: 'string',
          description: 'The name of the bookmark to navigate to',
        },
      },
      required: ['name'],
    },
    execute: async args => {
      const { name } = args
      return Word.run(async context => {
        const bookmarkName = name.replace(/\s+/g, '_')
        const contentControls = context.document.contentControls
        contentControls.load(['items'])
        await context.sync()

        for (const cc of contentControls.items) {
          cc.load(['tag', 'title'])
          await context.sync()

          if (cc.tag === `bookmark_${bookmarkName}` || cc.title === bookmarkName) {
            cc.select()
            await context.sync()
            return `Successfully navigated to bookmark: ${bookmarkName}`
          }
        }

        return `Bookmark not found: ${bookmarkName}`
      })
    },
  },

  insertContentControl: {
    name: 'insertContentControl',
    description:
      'Insert a content control (a container for content) at the current selection. Useful for creating structured documents.',
    inputSchema: {
      type: 'object',
      properties: {
        title: {
          type: 'string',
          description: 'The title of the content control',
        },
        tag: {
          type: 'string',
          description: 'Optional tag for programmatic identification',
        },
        appearance: {
          type: 'string',
          description: 'Visual appearance of the control',
          enum: ['BoundingBox', 'Tags', 'Hidden'],
        },
      },
      required: ['title'],
    },
    execute: async args => {
      const { title, tag, appearance = 'BoundingBox' } = args
      return Word.run(async context => {
        const range = context.document.getSelection()
        const contentControl = range.insertContentControl()
        contentControl.title = title
        if (tag) contentControl.tag = tag
        contentControl.appearance = appearance as Word.ContentControlAppearance

        await context.sync()
        return `Successfully inserted content control: ${title}`
      })
    },
  },

  findText: {
    name: 'findText',
    description: 'Find text in the document and return information about matches. Does not modify the document.',
    inputSchema: {
      type: 'object',
      properties: {
        searchText: {
          type: 'string',
          description:
            'The visible text to search for. Newlines are stripped automatically; search works across paragraphs.',
        },
        matchCase: {
          type: 'boolean',
          description: 'Whether to match case (default: false)',
        },
      },
      required: ['searchText'],
    },
    execute: async args => {
      const { searchText: rawSearch, matchCase = false } = args
      const searchText = stripNewlines(rawSearch)
      return Word.run(async context => {
        const { parsed } = await getDocumentParsed(context)
        const { cleanText, boundaries } = parsed
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
            contextBefore: sliceToDisplay(cleanText, boundaries, Math.max(0, idx - CTX), idx),
            contextAfter: sliceToDisplay(cleanText, boundaries, end + 1, Math.min(cleanText.length, end + 1 + CTX)),
            hasBoundaries,
          })
          pos = idx + 1
        }

        return JSON.stringify(
          {
            searchText,
            matchCount: matches.length,
            found: matches.length > 0,
            matches,
          },
          null,
          2,
        )
      })
    },
  },

  findAndSelectText: {
    name: 'findAndSelectText',
    description:
      'Find text in the document and select the first occurrence. Use this for SHORT selections (below 20 sentences). After selection, the user will see the text highlighted in Word.',
    inputSchema: {
      type: 'object',
      properties: {
        searchText: {
          type: 'string',
          description:
            'The visible text to search for. Newlines are stripped automatically; search works across paragraphs.',
        },
        matchCase: {
          type: 'boolean',
          description: 'Whether to match case (default: false)',
        },
      },
      required: ['searchText'],
    },
    execute: async args => {
      const { searchText: rawSearch, matchCase = false } = args
      const searchText = stripNewlines(rawSearch)
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
  },

  selectBetweenText: {
    name: 'selectBetweenText',
    description:
      'Anchor-based range expansion tool to select text between two text markers. Use this for LARGE selections (over a page/20+ sentences). IMPORTANT: Both anchors must be unique multi-word phrases (at least 3-5 words), not single words.',
    inputSchema: {
      type: 'object',
      properties: {
        startText: {
          type: 'string',
          description:
            'Unique multi-word phrase (3-5+ words) marking selection start. Newlines are stripped automatically. Example: "In the previous section" not just "section".',
        },
        endText: {
          type: 'string',
          description:
            'Unique multi-word phrase (3-5+ words) marking selection end. Newlines are stripped automatically.',
        },
        matchCase: {
          type: 'boolean',
          description: 'Whether to match case (default: false)',
        },
      },
      required: ['startText', 'endText'],
    },
    execute: async args => {
      const { startText: rawStart, endText: rawEnd, matchCase = false } = args
      const startText = stripNewlines(rawStart)
      const endText = stripNewlines(rawEnd)
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
        await context.sync()

        return JSON.stringify(
          {
            success: true,
            message: `Selected range from "${startText}" to "${endText}"`,
          },
          null,
          2,
        )
      })
    },
  },

  setParagraphFormat: {
    name: 'setParagraphFormat',
    description: 'Apply paragraph formatting (alignment, spacing, indentation) to selected paragraphs.',
    inputSchema: {
      type: 'object',
      properties: {
        alignment: {
          type: 'string',
          description: 'Paragraph alignment',
          enum: ['Left', 'Centered', 'Right', 'Justified'],
        },
        lineSpacing: {
          type: 'number',
          description: 'Line spacing in points (e.g., 12 for single, 24 for double with 12pt font)',
        },
        spaceBefore: {
          type: 'number',
          description: 'Space before paragraph in points',
        },
        spaceAfter: {
          type: 'number',
          description: 'Space after paragraph in points',
        },
        firstLineIndent: {
          type: 'number',
          description: 'First line indent in points (negative for hanging indent)',
        },
        leftIndent: {
          type: 'number',
          description: 'Left indent in points',
        },
        rightIndent: {
          type: 'number',
          description: 'Right indent in points',
        },
      },
      required: [],
    },
    execute: async args => {
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
  },

  setStyle: {
    name: 'setStyle',
    description: 'Apply a built-in Word style to the currently selected text or paragraphs.',
    inputSchema: {
      type: 'object',
      properties: {
        style: {
          type: 'string',
          description: 'The built-in style to apply',
          enum: [
            'Normal',
            'Heading1',
            'Heading2',
            'Heading3',
            'Heading4',
            'Title',
            'Subtitle',
            'Quote',
            'IntenseQuote',
            'ListParagraph',
            'NoSpacing',
          ],
        },
      },
      required: ['style'],
    },
    execute: async args => {
      const { style } = args
      return Word.run(async context => {
        const range = context.document.getSelection()
        range.styleBuiltIn = style as Word.BuiltInStyleName
        await context.sync()
        return `Successfully applied style: ${style}`
      })
    },
  },

  insertComment: {
    name: 'insertComment',
    description:
      'Add a comment to the currently selected text in the Word document. Requires text to be selected first.',
    inputSchema: {
      type: 'object',
      properties: {
        comment: {
          type: 'string',
          description: 'The comment text to add to the selected text',
        },
      },
      required: ['comment'],
    },
    execute: async args => {
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
  },
}

export function createWordTools(enabledTools?: WordToolName[]) {
  const tools = Object.entries(wordToolDefinitions)
    .filter(([name]) => !enabledTools || enabledTools.includes(name as WordToolName))
    .map(([, def]) => {
      const schemaObj: Record<string, z.ZodTypeAny> = {}

      for (const [propName, prop] of Object.entries(def.inputSchema.properties)) {
        let zodType: z.ZodTypeAny

        switch (prop.type) {
          case 'string':
            zodType = prop.enum ? z.enum(prop.enum as [string, ...string[]]) : z.string()
            break
          case 'number':
            zodType = z.number()
            break
          case 'boolean':
            zodType = z.boolean()
            break
          case 'array':
            zodType = z.array(z.any())
            break
          default:
            zodType = z.any()
        }

        if (prop.description) {
          zodType = zodType.describe(prop.description)
        }

        if (!def.inputSchema.required?.includes(propName)) {
          zodType = zodType.optional()
        }

        schemaObj[propName] = zodType
      }

      return tool(
        async input => {
          try {
            return await def.execute(input)
          } catch (error: any) {
            return `Error: ${error.message || 'Unknown error occurred'}`
          }
        },
        {
          name: def.name,
          description: def.description,
          schema: z.object(schemaObj),
        },
      )
    })

  return tools
}

export function getWordToolDefinitions(): WordToolDefinition[] {
  return Object.values(wordToolDefinitions)
}

export function getWordTool(name: WordToolName): WordToolDefinition | undefined {
  return wordToolDefinitions[name]
}

/**
 * Read the current Word selection as clean text (tracked-change deletions stripped).
 * Use this instead of `range.text` anywhere selection text is passed to the LLM.
 */
export async function getCleanSelectedText(): Promise<string> {
  return Word.run(async context => {
    const sel = context.document.getSelection()
    const ooxmlResult = sel.getOoxml()
    await context.sync()
    return sanitizeWordText(toDisplayText(parseOoxml(ooxmlResult.value)))
  })
}

export { wordToolDefinitions }
