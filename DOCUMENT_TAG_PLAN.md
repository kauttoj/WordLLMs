# Plan: Document Boundary Tags for LLM Visibility Control

## Problem

When writing large documents in Microsoft Word, the LLM agent reads the full document via tools like `getDocumentContent`. This includes potentially large non-relevant sections that are not relevant for the task (say, user want to work on Section 1 only instead of all 10 Sections include in the document). In such case, those additional parts of the document result in:
- Adding noise and irrelevant context to LLM requests, content rot may occur
- Waste tokens on content the user isn't actively working on
- May confuse the LLM about what parts of the document need attention

There is no way for users to tell the LLM "only look at this part of the document." The LLM always sees everything.

## Solution

Add special boundary tags that users type as literal text in their Word document to define which region the LLM can see and operate on. The LLM itself never learns about these boundaries — it simply sees a smaller document. Those special tags are used by the typescript frontend code serving between document and LLMs in the backend.

### Tag Semantics

For now, users place at most one `<wordllms_start>` and/or one `<wordllms_end>`:

| Tags present | Visible region |
|---|---|
| Neither | Full document (no change in current behavior) |
| `<wordllms_end>` only | Document start → tag |
| `<wordllms_start>` only | Tag → document end |
| Both (start must come first) | Between the two tags |
| Both (wrong order) | Error thrown |

### Example

A document with appendices:
```
Introduction
This is the main manuscript body...
Conclusion
<wordllms_end>
Appendix A: Raw data tables...
Appendix B: Supplementary figures...
```

The LLM only ever sees:
```
Introduction
This is the main manuscript body...
Conclusion
```

### Key Design Decisions

1. **LLM is unaware**: No boundary tag mentions in tool descriptions, no notes appended to output. The LLM sees a smaller document and has no concept of hidden content.

2. **Post-filter approach**: Tools run their normal logic on the full document, then a post-filter restricts results and actions to the visible region. If no tags exist, the filter is a no-op.

3. **User can still select anything**: The user has full access to their document. But if the LLM reads selected text, only the portion within the visible region is returned (empty if entirely outside).

4. **Single visible region**: At most one start and one end boundary. No multiple regions or toggle semantics.

5. **Error on wrong order**: If `<wordllms_end>` appears before `<wordllms_start>`, throw an error (per project principle: crash hard when assumptions aren't met).

## Files to Modify

**`src/frontend/utils/wordTools.ts`** — add 2 helpers, modify ~10 tool execute functions

**`src/backend/tools/word_tools.py`** — NO changes (LLM must not know about boundaries)

## Implementation

### Two Helper Functions (insert after `sanitizeWordText()`, line 15)

**Helper 1: `getVisibleTextRange(text)`** — text-level boundary detection for tools that work with cleanText/displayText character positions.

```typescript
const BOUNDARY_END_TAG = '<wordllms_end>'
const BOUNDARY_START_TAG = '<wordllms_start>'

interface VisibleRange { start: number; end: number }

/**
 * Find the visible character range in a text string based on boundary tags.
 * Returns null if no tags (full text is visible). Throws if tags are in wrong order.
 */
function getVisibleTextRange(text: string): VisibleRange | null {
  const startIdx = text.indexOf(BOUNDARY_START_TAG)
  const endIdx = text.indexOf(BOUNDARY_END_TAG)
  if (startIdx === -1 && endIdx === -1) return null
  if (startIdx !== -1 && endIdx !== -1) {
    if (startIdx >= endIdx)
      throw new Error('<wordllms_start> must appear before <wordllms_end> in the document.')
    return { start: startIdx + BOUNDARY_START_TAG.length, end: endIdx }
  }
  if (endIdx !== -1) return { start: 0, end: endIdx }
  return { start: startIdx + BOUNDARY_START_TAG.length, end: text.length }
}
```

**Helper 2: `getVisibleWordRange(context, body)`** — Word Range-level boundary detection for tools that resolve to Word Ranges and need to post-filter them using Office.js `compareLocationWith`.

```typescript
/**
 * Find the visible document region as a Word.Range.
 * Returns null if no boundary tags (full document visible). Throws if wrong order.
 */
async function getVisibleWordRange(
  context: Word.RequestContext,
  body: Word.Body,
): Promise<Word.Range | null> {
  const endResults = body.search(BOUNDARY_END_TAG, { matchCase: true, matchWildcards: false })
  const startResults = body.search(BOUNDARY_START_TAG, { matchCase: true, matchWildcards: false })
  endResults.load('items')
  startResults.load('items')
  await context.sync()
  const hasEnd = endResults.items.length > 0
  const hasStart = startResults.items.length > 0
  if (!hasEnd && !hasStart) return null
  if (hasStart && hasEnd) {
    const cmp = startResults.items[0].compareLocationWith(endResults.items[0])
    await context.sync()
    if (cmp.value !== 'Before' && cmp.value !== 'AdjacentBefore')
      throw new Error('<wordllms_start> must appear before <wordllms_end> in the document.')
    return startResults.items[0].getRange('End').expandTo(endResults.items[0].getRange('Start'))
  }
  if (hasEnd) return body.getRange('Start').expandTo(endResults.items[0].getRange('Start'))
  return startResults.items[0].getRange('End').expandTo(body.getRange('End'))
}
```

### Tool Modifications

#### `getDocumentContent` (line 665) — slice output to visible region

```typescript
execute: async () => {
  return Word.run(async context => {
    const { parsed } = await getDocumentParsed(context)
    const fullText = sanitizeWordText(toDisplayText(parsed))
    const vis = getVisibleTextRange(fullText)
    return vis ? fullText.slice(vis.start, vis.end) : fullText
  })
},
```

#### `findText` (line 1517) — search only within visible range, clip context

Search cleanText within visible boundaries only. Adjust match indices to be relative to visible start (consistent with `getDocumentContent` output). Clip context snippets to visible boundaries.

```typescript
execute: async args => {
  const { searchText: rawSearch, matchCase = false } = args
  const searchText = stripNewlines(rawSearch)
  return Word.run(async context => {
    const { parsed } = await getDocumentParsed(context)
    const { cleanText, boundaries } = parsed
    const vis = getVisibleTextRange(cleanText)
    const searchFrom = vis?.start ?? 0
    const searchTo = vis?.end ?? cleanText.length
    const CTX = 30
    const target = matchCase ? searchText : searchText.toLowerCase()
    const haystack = matchCase ? cleanText : cleanText.toLowerCase()
    const matches: FindMatch[] = []

    let pos = searchFrom
    while (true) {
      const idx = haystack.indexOf(target, pos)
      if (idx === -1 || idx + searchText.length > searchTo) break
      const end = idx + searchText.length - 1
      let hasBoundaries = false
      for (let i = idx + 1; i <= end; i++) {
        if (boundaries[i]) { hasBoundaries = true; break }
      }
      const ctxStart = Math.max(searchFrom, idx - CTX)
      const ctxEnd = Math.min(searchTo, end + 1 + CTX)
      matches.push({
        index: idx - searchFrom,
        contextBefore: sliceToDisplay(cleanText, boundaries, ctxStart, idx),
        contextAfter: sliceToDisplay(cleanText, boundaries, end + 1, ctxEnd),
        hasBoundaries,
      })
      pos = idx + 1
    }
    return JSON.stringify({ searchText, matchCount: matches.length, found: matches.length > 0, matches }, null, 2)
  })
},
```

#### `findAndSelectText` (line 1582) — post-filter resolved Word Ranges

Run normal resolution on full document, then post-filter to visible region:

```typescript
execute: async args => {
  const { searchText: rawSearch, matchCase = false } = args
  const searchText = stripNewlines(rawSearch)
  return Word.run(async context => {
    const { body, parsed } = await getDocumentParsed(context)
    const target = matchCase ? searchText : searchText.toLowerCase()
    const haystack = matchCase ? parsed.cleanText : parsed.cleanText.toLowerCase()
    if (haystack.indexOf(target) === -1) {
      return JSON.stringify({ success: false, message: `No matches found for "${searchText}"`, matchCount: 0 }, null, 2)
    }

    const ranges = await resolveAllOccurrencesCaseAware(context, body, parsed, searchText, matchCase)

    // Post-filter to visible region
    const visRange = await getVisibleWordRange(context, body)
    let filtered = ranges
    if (visRange && ranges.length > 0) {
      const cmps = ranges.map(r => visRange.compareLocationWith(r))
      await context.sync()
      filtered = ranges.filter((_, i) => cmps[i].value === 'Contains' || cmps[i].value === 'Equal')
    }

    if (filtered.length === 0) {
      return JSON.stringify({ success: false, message: `No matches found for "${searchText}"`, matchCount: 0 }, null, 2)
    }

    filtered[0].select()
    await context.sync()
    return JSON.stringify({
      success: true,
      message: `Selected first occurrence of "${searchText}" (found ${filtered.length} total matches)`,
      matchCount: filtered.length, selectedIndex: 0,
    }, null, 2)
  })
},
```

#### `searchAndReplace` (line 914) — replace only visible matches

Same pattern: resolve all, post-filter, replace only visible:

```typescript
execute: async args => {
  const { searchText: rawSearch, replaceText, matchCase = false } = args
  const searchText = stripNewlines(rawSearch)
  return Word.run(async context => {
    const { body, parsed } = await getDocumentParsed(context)
    const ranges = await resolveAllOccurrencesCaseAware(context, body, parsed, searchText, matchCase)

    // Post-filter to visible region
    const visRange = await getVisibleWordRange(context, body)
    let filtered = ranges
    if (visRange && ranges.length > 0) {
      const cmps = ranges.map(r => visRange.compareLocationWith(r))
      await context.sync()
      filtered = ranges.filter((_, i) => cmps[i].value === 'Contains' || cmps[i].value === 'Equal')
    }

    if (filtered.length === 0) return `No occurrences of "${searchText}" found in document`
    for (let i = filtered.length - 1; i >= 0; i--) {
      await trackedReplace(context, filtered[i], replaceText)
    }
    return `Replaced ${filtered.length} occurrence(s) of "${searchText}" with "${replaceText}"`
  })
},
```

#### `selectBetweenText` (line 1656) — scope anchor search to visible region

Replace `countOccurrences` and `indexOf` calls with visible-region-scoped versions:

```typescript
execute: async args => {
  const { startText: rawStart, endText: rawEnd, matchCase = false } = args
  const startText = stripNewlines(rawStart)
  const endText = stripNewlines(rawEnd)
  return Word.run(async context => {
    const { body, parsed } = await getDocumentParsed(context)
    const { cleanText } = parsed
    const vis = getVisibleTextRange(cleanText)
    const from = vis?.start ?? 0
    const to = vis?.end ?? cleanText.length
    const haystack = matchCase ? cleanText : cleanText.toLowerCase()
    const startNeedle = matchCase ? startText : startText.toLowerCase()
    const endNeedle = matchCase ? endText : endText.toLowerCase()

    // Count only visible occurrences for uniqueness check
    const countIn = (needle: string) => {
      let c = 0, p = from
      while (true) {
        const i = haystack.indexOf(needle, p)
        if (i === -1 || i + needle.length > to) break
        c++; p = i + 1
      }
      return c
    }
    const startCount = countIn(startNeedle)
    // ... (same validation logic as current, using countIn instead of countOccurrences)
    // ... indexOf calls use `from` as start position and check against `to`
    // ... rest of the function stays the same (resolveCleanTextToRange, etc.)
  })
},
```

#### `searchAndReplaceInSelection` (line 957) — post-filter both paths

Add post-filter after both the fast path (`selection.search`) and OOXML fallback path, before replacing:

```typescript
// After getting results from either path, before replacing:
const visRange = await getVisibleWordRange(context, body)
if (visRange) {
  const cmps = results.map(r => visRange.compareLocationWith(r))
  await context.sync()
  results = results.filter((_, i) => cmps[i].value === 'Contains' || cmps[i].value === 'Equal')
}
```

#### `getSelectedText` (line 646) — clip selection to visible region

Return only the portion of the selection within the visible region. Return empty if entirely outside:

```typescript
execute: async () => {
  return Word.run(async context => {
    const body = context.document.body
    const sel = context.document.getSelection()
    const visRange = await getVisibleWordRange(context, body)

    if (!visRange) {
      // No boundaries — return full selection as before
      const ooxmlResult = sel.getOoxml()
      await context.sync()
      return sanitizeWordText(toDisplayText(parseOoxml(ooxmlResult.value)))
    }

    // Check overlap between selection and visible range
    const cmp = sel.compareLocationWith(visRange)
    await context.sync()
    if (cmp.value === 'Before' || cmp.value === 'After'
     || cmp.value === 'AdjacentBefore' || cmp.value === 'AdjacentAfter') {
      return ''  // Entirely outside visible region
    }

    // Clip selection to visible range (compute intersection)
    const selStart = sel.getRange('Start')
    const visStart = visRange.getRange('Start')
    const sCmp = selStart.compareLocationWith(visStart)
    await context.sync()
    const intStart = (sCmp.value === 'Before' || sCmp.value === 'AdjacentBefore') ? visStart : selStart

    const selEnd = sel.getRange('End')
    const visEnd = visRange.getRange('End')
    const eCmp = selEnd.compareLocationWith(visEnd)
    await context.sync()
    const intEnd = (eCmp.value === 'After' || eCmp.value === 'AdjacentAfter') ? visEnd : selEnd

    const intersection = intStart.expandTo(intEnd)
    const ooxmlResult = intersection.getOoxml()
    await context.sync()
    return sanitizeWordText(toDisplayText(parseOoxml(ooxmlResult.value)))
  })
},
```

#### `selectText` (line 1279) — select visible range only

```typescript
execute: async args => {
  const { scope } = args
  return Word.run(async context => {
    if (scope === 'All') {
      const body = context.document.body
      const visRange = await getVisibleWordRange(context, body)
      ;(visRange ?? body).select()
      await context.sync()
      return 'Successfully selected all text'
    }
    return 'Invalid scope'
  })
},
```

#### `getDocumentProperties` (line 1027) — stats on visible text

```typescript
execute: async () => {
  return Word.run(async context => {
    const { parsed } = await getDocumentParsed(context)
    const displayText = toDisplayText(parsed)
    const vis = getVisibleTextRange(displayText)
    const visibleText = vis ? displayText.slice(vis.start, vis.end) : displayText
    const paragraphs = visibleText.split('\n').filter(line => line.length > 0)
    const wordCount = visibleText.split(/\s+/).filter(w => w.length > 0).length
    return JSON.stringify({
      paragraphCount: paragraphs.length,
      wordCount,
      characterCount: visibleText.replace(/\n/g, '').length,
    }, null, 2)
  })
},
```

### Unchanged

- **`getCleanSelectedText()` export** (line 1921) — user-initiated chat input, user chooses what to share
- **Backend tool descriptions** — LLM must not know about boundaries
- **`getRangeInfo`** — reads current selection properties; if selection was constrained by above changes, this is already correct
- **Insert/format/delete tools** — operate on cursor/selection position; LLM can only reach visible positions through filtered search/select tools
- **`goToBookmark`** — named entity navigation, not text-position-based

## Summary of Changes

| What | Type |
|---|---|
| `getVisibleTextRange()` | New helper (~15 lines) |
| `getVisibleWordRange()` | New helper (~20 lines) |
| `getDocumentContent` | +2 lines (slice output) |
| `findText` | ~10 lines changed (search within visible range, clip context) |
| `findAndSelectText` | +8 lines (post-filter resolved ranges) |
| `searchAndReplace` | +8 lines (post-filter resolved ranges) |
| `selectBetweenText` | ~10 lines changed (search/count within visible range) |
| `searchAndReplaceInSelection` | +5 lines (post-filter) |
| `getSelectedText` | Rewritten (~25 lines, clips selection to visible range) |
| `selectText` | +2 lines (select visible range) |
| `getDocumentProperties` | ~5 lines changed (stats on visible text) |

## Verification

1. Type text, then `<wordllms_end>`, then appendix — agent sees only text before tag
2. Search for text only in appendix — 0 matches
3. "Find and select [visible text]" — selects correctly, doesn't select hidden match
4. "Replace [text]" — only replaces in visible region, hidden occurrences untouched
5. Select text across boundary → `getSelectedText` returns only visible portion
6. Select text entirely in hidden region → returns empty
7. Test `<wordllms_start>` only, `<wordllms_end>` only, and both
8. Put `<wordllms_end>` before `<wordllms_start>` → error thrown
9. No tags → identical behavior to current (no regression)
10. `yarn build` passes
