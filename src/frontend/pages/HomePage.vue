<template>
  <CheckPointsPage
    v-if="showCheckpoints"
    :thread-id="threadId"
    :current-checkpoint-id="currentCheckpointId"
    @close="showCheckpoints = false"
    @restore="handleRestore"
    @select-thread="handleSelectThread"
  />
  <div
    v-show="!showCheckpoints"
    class="items-center relative flex h-full w-full flex-col justify-center bg-bg-secondary p-1"
  >
    <div class="relative flex h-full w-full flex-col gap-1 rounded-md">
      <!-- Header -->
      <div class="flex justify-between rounded-sm p-1">
        <div class="flex flex-1 items-center gap-2 text-accent">
          <img src="/logo.svg" alt="WordLLMs" class="h-[36px] w-auto" />
        </div>
        <div class="flex items-center gap-1 rounded-md border border-accent/10">
          <CustomButton
            :title="t('newChat')"
            :icon="Plus"
            text=""
            type="secondary"
            class="border-none p-1!"
            :icon-size="18"
            :disabled="loading"
            @click="startNewChat"
          />
          <CustomButton
            :title="t('settings')"
            :icon="Settings"
            text=""
            type="secondary"
            class="border-none p-1!"
            :icon-size="18"
            :disabled="loading"
            @click="settings"
          />
          <CustomButton
            :title="t('checkPoints')"
            :icon="History"
            text=""
            type="secondary"
            class="border-none p-1!"
            :icon-size="18"
            :disabled="loading"
            @click="checkPoints"
          />
        </div>
      </div>

      <!-- Read-Only Mode Banner -->
      <div
        v-if="readOnlyMode && mode !== 'ask'"
        class="flex items-center justify-center gap-1.5 rounded-md bg-amber-500/15 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400"
      >
        <Lock :size="12" />
        <span>{{ $t('readOnlyBanner') }}</span>
      </div>

      <!-- Quick Actions Bar -->
      <div class="flex w-full items-center justify-center gap-2 flex-wrap rounded-md">
        <CustomButton
          v-for="slot in enabledQuickActionSlots"
          :key="slot.id"
          :title="slot.name"
          text=""
          :icon="ICON_OPTIONS[slot.icon] || ICON_OPTIONS['Sparkle']"
          type="secondary"
          :icon-size="16"
          class="shrink-0! bg-surface! p-1.5!"
          :disabled="loading"
          @click="applyQuickActionSlot(slot)"
        />
        <SingleSelect
          v-model="activeSystemPromptId"
          :key-list="['', ...systemPromptPresets.map(p => p.id)]"
          :placeholder="t('selectSystemPrompt')"
          :display-value="activeSystemPromptDisplayName"
          title=""
          :fronticon="false"
          class="max-w-xs! flex-1! bg-surface! text-xs!"
          @change="onSystemPromptSelected"
        >
          <template #item="{ item }">
            {{ item === '' ? t('noSystemPrompt') : systemPromptPresets.find(p => p.id === item)?.name || item }}
          </template>
        </SingleSelect>
      </div>

      <!-- Chat Messages Container -->
      <div
        ref="messagesContainer"
        :style="{ height: messagesHeight + '%', minHeight: '100px', maxHeight: 'calc(100% - 180px)' }"
        class="flex flex-col gap-1 overflow-y-auto rounded-md border border-border-secondary bg-surface p-2 shadow-sm"
      >
        <div
          v-if="history.length === 0"
          class="flex h-full flex-col items-center justify-center gap-4 p-8 text-center text-accent"
        >
          <Sparkles :size="32" />
          <p class="font-semibold text-main">
            {{ $t('emptyTitle') }}
          </p>
          <p class="text-xs font-semibold text-secondary">
            {{ $t('emptySubtitle') }}
          </p>
        </div>

        <template v-for="(entry, gIdx) in groupedDisplayHistory" :key="'g-' + gIdx">
          <!-- Tool Call Group: consecutive tool calls rendered together -->
          <div v-if="entry.kind === 'tool-group'" class="flex flex-col items-start gap-1">
            <div v-if="shouldShowBotHeader(entry.items[0].displayIndex)" class="mb-1 flex items-center gap-2">
              <div
                class="flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold"
                :class="getBotStyles(getBotMetadata(entry.items[0].displayIndex)!.botType, getBotMetadata(entry.items[0].displayIndex)!.botName).header"
              >
                <span>{{ getBotMetadata(entry.items[0].displayIndex)!.emoji }}</span>
                <span>{{ getBotMetadata(entry.items[0].displayIndex)!.botName }}</span>
              </div>
              <span v-if="getBotMetadata(entry.items[0].displayIndex)!.roundNumber" class="text-xs text-secondary">
                Round {{ getBotMetadata(entry.items[0].displayIndex)!.roundNumber }}
              </span>
            </div>
            <div
              class="flex items-start gap-1"
              :class="settingForm.horizontalToolCalls ? 'flex-row flex-wrap' : 'flex-col'"
            >
              <div
                v-for="item in entry.items"
                :key="item.displayIndex"
                class="tool-call-bubble border"
                :class="
                  getBotMetadata(item.displayIndex)
                    ? getBotStyles(getBotMetadata(item.displayIndex)!.botType, getBotMetadata(item.displayIndex)!.botName).bubble
                    : 'border-border-secondary bg-bg-tertiary'
                "
              >
                <span class="tool-icon">🔧</span>
                <span class="tool-name">{{ item.msg.toolName }}</span>
              </div>
            </div>
          </div>

          <!-- Regular user/assistant messages -->
          <div
            v-else
            v-show="!(entry.msg instanceof AIMessage) || cleanMessageText(entry.msg).length > 0"
            class="group flex items-end gap-4 [.user]:flex-row-reverse"
            :class="{
              assistant: entry.msg instanceof AIMessage,
              user: entry.msg instanceof HumanMessage,
              'mt-2': entry.displayIndex > 0,
            }"
          >
            <div
              class="flex min-w-0 flex-1 flex-col gap-1 group-[.assistant]:items-start group-[.assistant]:text-left group-[.user]:items-end group-[.user]:text-left"
            >
              <!-- Bot header for multiagent messages (skip for decision-only messages) -->
              <template v-if="shouldShowBotHeader(entry.displayIndex)">
                <div class="mb-1 flex items-center gap-2">
                  <div
                    class="flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold"
                    :class="getBotStyles(getBotMetadata(entry.displayIndex)!.botType, getBotMetadata(entry.displayIndex)!.botName).header"
                  >
                    <span>{{ getBotMetadata(entry.displayIndex)!.emoji }}</span>
                    <span>{{ getBotMetadata(entry.displayIndex)!.botName }}</span>
                  </div>
                  <span v-if="getBotMetadata(entry.displayIndex)!.roundNumber" class="text-xs text-secondary">
                    Round {{ getBotMetadata(entry.displayIndex)!.roundNumber }}
                  </span>
                </div>
              </template>
              <!-- Message bubble (hidden during edit) -->
              <div
                v-if="!(entry.msg instanceof HumanMessage && editingMessageIndex === entry.displayIndex)"
                class="group max-w-[95%] rounded-md border p-1 text-sm leading-[1.4] wrap-break-word text-main/90 shadow-sm group-[.assistant]:text-left group-[.user]:bg-accent/10"
                :class="[
                  entry.msg instanceof AIMessage && !getBotMetadata(entry.displayIndex) ? 'group-[.assistant]:bg-bg-tertiary' : '',
                  entry.msg instanceof AIMessage ? '' : 'border-border-secondary',
                  entry.msg instanceof AIMessage && getBotMetadata(entry.displayIndex)
                    ? getBotStyles(getBotMetadata(entry.displayIndex)!.botType, getBotMetadata(entry.displayIndex)!.botName).bubble
                    : 'border-border-secondary',
                  settingForm.enableMarkdown ? 'markdown-body' : 'whitespace-pre-wrap',
                ]"
              >
                <template v-for="(segment, idx) in renderSegments(entry.msg)" :key="idx">
                  <template v-if="segment.type === 'text'">
                    <div v-if="settingForm.enableMarkdown" v-html="renderMarkdown(segment.text.trim())" />
                    <span v-else>{{ segment.text.trim() }}</span>
                  </template>
                  <details v-else class="mb-1 rounded-sm border border-border-secondary bg-bg-secondary">
                    <summary class="cursor-pointer list-none p-1 text-sm font-semibold text-secondary">
                      Thought process
                    </summary>
                    <pre class="m-0 p-1 text-xs wrap-break-word whitespace-pre-wrap text-secondary">{{
                      segment.text.trim()
                    }}</pre>
                  </details>
                </template>
              </div>
              <!-- Edit textarea (shown during edit) -->
              <textarea
                v-if="entry.msg instanceof HumanMessage && editingMessageIndex === entry.displayIndex"
                v-model="editText"
                :ref="(el: any) => { editTextareaEl = el as HTMLTextAreaElement | null }"
                class="w-full max-w-[95%] resize-none overflow-y-hidden rounded-md border border-accent/30 bg-bg-secondary p-1 text-sm text-main"
                @keydown.ctrl.enter="submitEdit"
                @input="(e) => resizeEditTextarea(e.target as HTMLTextAreaElement)"
              />
              <!-- Attachment indicators for user messages -->
              <div
                v-if="entry.msg instanceof HumanMessage && getMessageAttachments(entry.displayIndex)?.length"
                class="flex flex-wrap gap-1"
              >
                <div
                  v-for="(att, aidx) in getMessageAttachments(entry.displayIndex)"
                  :key="aidx"
                  class="flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] text-accent"
                >
                  <Paperclip :size="10" />
                  <span class="max-w-20 truncate">{{ att.filename }}</span>
                </div>
              </div>
              <!-- User message action buttons -->
              <div v-if="entry.msg instanceof HumanMessage" class="flex gap-1">
                <template v-if="editingMessageIndex === entry.displayIndex">
                  <CustomButton
                    :title="t('confirm')"
                    text=""
                    :icon="CheckCircle"
                    type="secondary"
                    class="bg-surface! p-1.5! text-secondary!"
                    :icon-size="12"
                    @click="submitEdit"
                  />
                  <CustomButton
                    :title="t('cancel')"
                    text=""
                    :icon="X"
                    type="secondary"
                    class="bg-surface! p-1.5! text-secondary!"
                    :icon-size="12"
                    @click="cancelEdit"
                  />
                </template>
                <template v-else>
                  <CustomButton
                    :title="t('edit')"
                    text=""
                    :icon="Pencil"
                    type="secondary"
                    class="bg-surface! p-1.5! text-secondary!"
                    :icon-size="12"
                    :disabled="loading"
                    @click="startEdit(entry.displayIndex)"
                  />
                  <CustomButton
                    :title="t('fork')"
                    text=""
                    :icon="GitFork"
                    type="secondary"
                    class="bg-surface! p-1.5! text-secondary!"
                    :icon-size="12"
                    :disabled="loading"
                    @click="forkFromMessage(entry.displayIndex)"
                  />
                  <CustomButton
                    v-if="isLastHumanMessage(entry.displayIndex)"
                    :title="t('retry')"
                    text=""
                    :icon="RotateCcw"
                    type="secondary"
                    class="bg-surface! p-1.5! text-secondary!"
                    :icon-size="12"
                    :disabled="loading"
                    @click="retryLastMessage"
                  />
                  <CustomButton
                    :title="t('copyToClipboard')"
                    text=""
                    :icon="Copy"
                    type="secondary"
                    class="bg-surface! p-1.5! text-secondary!"
                    :icon-size="12"
                    @click="copyToClipboard(cleanMessageText(entry.msg))"
                  />
                </template>
              </div>
              <div v-if="entry.msg instanceof AIMessage" class="flex gap-1">
                <CustomButton
                  :title="t('replaceSelectedText')"
                  text=""
                  :icon="FileText"
                  type="secondary"
                  class="bg-surface! p-1.5! text-secondary!"
                  :icon-size="12"
                  @click="insertToDocument(cleanMessageText(entry.msg), 'replace')"
                />
                <CustomButton
                  :title="t('appendToSelection')"
                  text=""
                  :icon="Plus"
                  type="secondary"
                  class="bg-surface! p-1.5! text-secondary!"
                  :icon-size="12"
                  @click="insertToDocument(cleanMessageText(entry.msg), 'append')"
                />
                <CustomButton
                  :title="t('copyToClipboard')"
                  text=""
                  :icon="Copy"
                  type="secondary"
                  class="bg-surface! p-1.5! text-secondary!"
                  :icon-size="12"
                  @click="copyToClipboard(cleanMessageText(entry.msg))"
                />
              </div>
            </div>
          </div>
        </template>
        <!-- Processing spinner -->
        <div v-if="loading" class="flex items-center gap-2 py-1 pl-1">
          <div class="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-white"></div>
          <span class="text-xs text-secondary">Processing... ({{ loadingTimeDisplay }}s)</span>
        </div>
      </div>
      <div class="text-right text-xs" :class="contextStatsWarning ? 'font-semibold text-red-500' : 'text-secondary'">{{ contextStatsDisplay }}</div>

      <!-- Draggable Separator -->
      <div
        class="separator-handle group relative z-10 flex h-2 w-full cursor-row-resize items-center justify-center"
        :class="{ 'separator-active': isDragging }"
        @mousedown="startDrag"
        @touchstart="startDrag"
      >
        <div class="h-1 w-12 rounded-full bg-border transition-colors group-hover:bg-accent"></div>
      </div>

      <!-- Input Area -->
      <div
        ref="inputAreaContainer"
        :style="{ height: 100 - messagesHeight + '%', minHeight: '80px' }"
        class="flex flex-col gap-1 overflow-hidden rounded-md"
      >
        <div class="flex items-center justify-between gap-2 overflow-hidden">
          <div class="flex shrink-0 gap-1 rounded-sm border border-border bg-surface p-0.5">
            <button
              class="cursor-po flex h-7 w-7 items-center justify-center rounded-md border-none text-secondary hover:bg-accent/30 hover:text-white! [.active]:text-accent"
              :class="{ active: mode === 'ask' }"
              title="Ask Mode"
              @click="mode = 'ask'"
            >
              <MessageSquare :size="14" />
            </button>
            <button
              class="cursor-po flex h-7 w-7 items-center justify-center rounded-md border-none text-secondary hover:bg-accent/30 hover:text-white! [.active]:text-accent"
              :class="{ active: mode === 'agent' }"
              title="Agent Mode"
              @click="mode = 'agent'"
            >
              <BotMessageSquare :size="17" />
            </button>
            <button
              class="cursor-po flex h-7 w-7 items-center justify-center rounded-md border-none text-secondary hover:bg-accent/30 hover:text-white! [.active]:text-accent"
              :class="{ active: mode === 'multiagent' }"
              title="MultiAgent Mode"
              @click="mode = 'multiagent'"
            >
              <Sparkles :size="16" />
            </button>
          </div>
          <div v-show="mode !== 'multiagent'" class="flex min-w-0 flex-1 gap-1 overflow-hidden">
            <select
              v-model="settingForm.api"
              class="h-7 max-w-full min-w-0 cursor-pointer rounded-md border border-border bg-surface p-1 text-xs text-secondary hover:border-accent focus:outline-none disabled:cursor-not-allowed disabled:bg-secondary"
            >
              <option v-for="item in settingPreset.api.optionObj" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
            <select
              v-show="shouldShowModelSelector"
              v-model="currentModelSelect"
              class="h-7 max-w-full min-w-0 cursor-pointer rounded-md border border-border bg-surface p-1 text-xs text-secondary hover:border-accent focus:outline-none"
            >
              <option v-for="item in currentModelOptions" :key="item" :value="item">
                {{ item }}
              </option>
            </select>
          </div>
          <div v-show="mode === 'multiagent'" class="flex min-w-0 flex-1 items-center gap-2 overflow-hidden text-xs">
            <label class="flex items-center gap-1 text-secondary">
              <span>Experts:</span>
              <select
                v-model="multiAgentExpertCount"
                class="h-7 min-w-0 cursor-pointer rounded-md border border-border bg-surface px-1 text-xs text-main hover:border-accent focus:outline-none"
              >
                <option v-for="n in availableExpertCounts" :key="n" :value="n">{{ n }}</option>
              </select>
            </label>
            <label class="flex items-center gap-1 text-secondary">
              <span>Mode:</span>
              <select
                v-model="multiAgentMode"
                class="h-7 min-w-0 cursor-pointer rounded-md border border-border bg-surface px-1 text-xs text-main hover:border-accent focus:outline-none"
              >
                <option value="parallel">Parallel</option>
                <option value="collaborative">Collaborative</option>
              </select>
            </label>
          </div>
        </div>
        <div
          class="flex min-w-12 flex-1 min-h-0 flex-col gap-1 rounded-md border border-border bg-surface p-2 focus-within:border-accent"
          @dragover="handleDragOver"
          @drop="handleDrop"
        >
          <input
            ref="fileInputRef"
            type="file"
            multiple
            class="hidden"
            accept=".txt,.md,.pdf,.docx,.pptx,.csv,.xlsx,.xls,.json,.xml,.yaml,.yml,.html,.htm,.epub,.py,.js,.ts,.tsx,.jsx,.css,.scss,.sql,.sh,.bat,.c,.cpp,.h,.hpp,.java,.go,.rs,.rb,.php,.toml,.ini,.log,.png,.jpg,.jpeg,.gif,.webp"
            @change="handleFileSelect"
          />
          <div v-if="pendingAttachments.length" class="flex flex-wrap gap-1">
            <div
              v-for="(att, idx) in pendingAttachments"
              :key="att.filename + idx"
              class="flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] text-accent"
            >
              <Paperclip :size="10" />
              <span class="max-w-20 truncate">{{ att.filename }}</span>
              <button
                class="flex h-3.5 w-3.5 items-center justify-center rounded-full border-none bg-transparent p-0 text-secondary hover:text-danger"
                @click="removeAttachment(idx)"
              >
                <X :size="10" />
              </button>
            </div>
          </div>
          <div class="flex flex-1 min-h-0 items-start gap-2">
            <textarea
              ref="inputTextarea"
              v-model="userInput"
              class="placeholder::text-secondary block flex-1 self-stretch resize-none overflow-y-auto border-none bg-transparent py-2 text-xs leading-normal text-main outline-none placeholder:text-xs"
              :placeholder="
                mode === 'ask'
                  ? $t('askAnything')
                  : mode === 'multiagent'
                    ? $t('directTheMultiagent')
                    : $t('directTheAgent')
              "
              @keydown.enter.exact.prevent="sendMessage"
            />
            <button
              class="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-sm border-none bg-transparent text-secondary hover:text-accent"
              :title="$t('attachFiles')"
              @click="openFileSelector"
            >
              <Paperclip :size="16" />
            </button>
            <button
              v-if="loading"
              class="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-sm border-none bg-danger text-white"
              title="Stop"
              @click="stopGeneration"
            >
              <Square :size="18" />
            </button>
            <button
              v-else
              class="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-sm border-none bg-accent text-white disabled:cursor-not-allowed disabled:bg-accent/50"
              title="Send"
              :disabled="!userInput.trim()"
              @click="sendMessage"
            >
              <Send :size="18" />
            </button>
          </div>
        </div>
        <div class="flex items-center gap-3 px-1">
          <label class="flex h-3.5 w-3.5 flex-1 cursor-pointer items-center gap-1 text-xs text-secondary">
            <input v-model="useWordFormatting" type="checkbox" />
            <span>{{ $t('useWordFormattingLabel') }}</span>
          </label>
          <label class="flex h-3.5 w-3.5 flex-1 cursor-pointer items-center gap-1 text-xs text-secondary">
            <input v-model="useSelectedText" type="checkbox" :checked="useSelectedText" />
            <span>{{ $t('includeSelectionLabel') }}</span>
          </label>
          <label
            v-show="mode !== 'ask'"
            class="flex h-3.5 w-3.5 flex-1 cursor-pointer items-center gap-1 text-xs text-secondary"
          >
            <input v-model="readOnlyMode" type="checkbox" />
            <span>{{ $t('readOnlyLabel') }}</span>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { AIMessage, HumanMessage, Message, SystemMessage } from '@langchain/core/messages'
import { useStorage } from '@vueuse/core'
import {
  BotMessageSquare,
  CheckCircle,
  Copy,
  FileText,
  GitFork,
  History,
  Lock,
  MessageSquare,
  Paperclip,
  Pencil,
  Plus,
  RotateCcw,
  Send,
  Settings,
  Sparkles,
  Square,
  X,
} from 'lucide-vue-next'
import { v4 as uuidv4 } from 'uuid'
import { computed, nextTick, onActivated, onBeforeMount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import {
  type BackendThread,
  editConversationMessage,
  fetchContextStats,
  fetchThread,
  forkConversation,
  saveThreadToBackend,
  setHistoryPath,
  truncateConversation,
} from '@/api/backend'
import { type CheckpointTuple, IndexedDBSaver, type SerializedMessage } from '@/api/checkpoints'
import { insertFormattedResult, insertResult } from '@/api/common'
import type { BotMetadata, MultiAgentConfig, MultiAgentExpertConfig } from '@/api/types'
import { getAgentResponse, getChatResponse, getMultiAgentResponse } from '@/api/union'
import CustomButton from '@/components/CustomButton.vue'
import SingleSelect from '@/components/SingleSelect.vue'
import CheckPointsPage from '@/pages/checkPointsPage.vue'
import { checkAuth } from '@/utils/common'
import {
  getQuickActionSlots,
  getSystemPromptPresets,
  ICON_OPTIONS,
  type QuickActionSlot,
  type SystemPromptPreset,
} from '@/utils/constant'
import { localStorageKey } from '@/utils/enum'
import { createGeneralTools, GeneralToolName } from '@/utils/generalTools'
import { renderMarkdown } from '@/utils/markdown'
import { message as messageUtil } from '@/utils/message'
import { ToolCallMessage } from '@/utils/messageTypes'
import useSettingForm from '@/utils/settingForm'
import { settingPreset } from '@/utils/settingPreset'
import { createWordTools, getCleanSelectedText, READ_ONLY_WORD_TOOLS, WordToolName } from '@/utils/wordTools'

const router = useRouter()
const { t } = useI18n()

const settingForm = useSettingForm()

// Quick action slots (configurable buttons)
const quickActionSlots = ref<QuickActionSlot[]>(getQuickActionSlots())
const enabledQuickActionSlots = computed(() => quickActionSlots.value.filter(s => s.enabled && s.name.trim()))

// System prompt presets (persistent behavioral instructions)
const systemPromptPresets = ref<SystemPromptPreset[]>(getSystemPromptPresets())
const activeSystemPromptId = ref<string>(localStorage.getItem('activeSystemPromptId') || '')
const additionalSystemPrompt = ref<string>('')

const activeSystemPromptDisplayName = computed(() => {
  if (!activeSystemPromptId.value) return ''
  return systemPromptPresets.value.find(p => p.id === activeSystemPromptId.value)?.name || ''
})

const customSystemPrompt = ref<string>('')

const allWordToolNames: WordToolName[] = [
  'getSelectedText',
  'getDocumentContent',
  'insertText',
  'replaceSelectedText',
  'appendText',
  'insertParagraph',
  'formatText',
  'searchAndReplace',
  'searchAndReplaceInSelection',
  'getDocumentProperties',
  'insertTable',
  'insertList',
  'deleteText',
  'clearFormatting',
  'setParagraphFormat',
  'setStyle',
  'insertPageBreak',
  'getRangeInfo',
  'selectText',
  'insertImage',
  'getTableInfo',
  'insertBookmark',
  'goToBookmark',
  'insertContentControl',
  'findText',
  'findAndSelectText',
  'selectBetweenText',
]

const allGeneralToolNames: GeneralToolName[] = ['webSearch', 'fetchWebContent', 'getCurrentDate', 'calculateMath']

// Tool state
const enabledWordTools = ref<WordToolName[]>(loadEnabledWordTools())
const enabledGeneralTools = ref<GeneralToolName[]>(loadEnabledGeneralTools())

function loadEnabledWordTools(): WordToolName[] {
  const stored = localStorage.getItem('enabledWordTools')
  if (stored) {
    try {
      const parsed = JSON.parse(stored)
      return parsed.filter((name: string) => allWordToolNames.includes(name as WordToolName))
    } catch {
      return [...allWordToolNames]
    }
  }
  return [...allWordToolNames]
}

function loadEnabledGeneralTools(): GeneralToolName[] {
  const stored = localStorage.getItem('enabledGeneralTools')
  if (stored) {
    try {
      const parsed = JSON.parse(stored)
      return parsed.filter((name: string) => allGeneralToolNames.includes(name as GeneralToolName))
    } catch {
      return [...allGeneralToolNames]
    }
  }
  return [...allGeneralToolNames]
}

// Reload settings when returning from Settings (keep-alive reactivation)
onActivated(() => {
  enabledWordTools.value = loadEnabledWordTools()
  enabledGeneralTools.value = loadEnabledGeneralTools()
  quickActionSlots.value = getQuickActionSlots()
  systemPromptPresets.value = getSystemPromptPresets()
  resolveActiveSystemPrompt()
})

function getActiveWordToolNames(): WordToolName[] {
  if (readOnlyMode.value) {
    return enabledWordTools.value.filter(name => READ_ONLY_WORD_TOOLS.includes(name))
  }
  return enabledWordTools.value
}

function getActiveTools() {
  const wordTools = createWordTools(getActiveWordToolNames())
  const generalTools = createGeneralTools(enabledGeneralTools.value)
  return [...generalTools, ...wordTools]
}

function resolveActiveSystemPrompt() {
  if (!activeSystemPromptId.value) {
    additionalSystemPrompt.value = ''
    return
  }
  const preset = systemPromptPresets.value.find(p => p.id === activeSystemPromptId.value)
  if (preset) {
    additionalSystemPrompt.value = preset.systemPrompt
  } else {
    // Preset was deleted — clear selection
    activeSystemPromptId.value = ''
    additionalSystemPrompt.value = ''
    localStorage.removeItem('activeSystemPromptId')
  }
}

function onSystemPromptSelected() {
  if (activeSystemPromptId.value) {
    localStorage.setItem('activeSystemPromptId', activeSystemPromptId.value)
  } else {
    localStorage.removeItem('activeSystemPromptId')
  }
  resolveActiveSystemPrompt()
}

async function applyQuickActionSlot(slot: QuickActionSlot) {
  const lang = settingForm.value.replyLanguage
  customSystemPrompt.value = slot.systemPrompt.replace(/\$\{language\}/g, lang)
  userInput.value = slot.userPrompt.replace(/\$\{language\}/g, lang)
  await nextTick()
  adjustTextareaHeight()
  inputTextarea.value?.focus()
}

// Chat state
const mode = useStorage(localStorageKey.chatMode, 'ask' as 'ask' | 'agent' | 'multiagent')
const history = ref<Message[]>([])
const messageMetadata = new Map<number, BotMetadata>() // Bot metadata for multiagent display
const messageAttachmentsMap = new Map<number, { filename: string }[]>() // Attachment filenames per message
const currentBotMessageIndex = ref<number | null>(null) // Track current bot message being streamed
const userInput = ref('')
const loading = ref(false)
const loadingElapsed = ref(0)
let loadingTimer: ReturnType<typeof setInterval> | null = null
const messagesContainer = ref<HTMLElement>()
const inputTextarea = ref<HTMLTextAreaElement>()
const inputAreaContainer = ref<HTMLDivElement>()
const abortController = ref<AbortController | null>(null)
const threadId = useStorage(localStorageKey.threadId, uuidv4())
const editingMessageIndex = ref<number | null>(null)
const editText = ref('')
let editTextareaEl: HTMLTextAreaElement | null = null
const showCheckpoints = ref(false)
const saver = new IndexedDBSaver()
const currentCheckpointId = ref<string>('')

// Context size tracking
const contextStats = ref({ chars: 0, tokens: 0 })
const liveCharsDelta = ref(0)
const currentTokenEstimate = computed(() => {
  let { tokens } = contextStats.value
  if (loading.value && liveCharsDelta.value > 0) {
    tokens += Math.round(liveCharsDelta.value / 4)
  }
  return tokens
})
const contextStatsDisplay = computed(() => {
  const fmt = (n: number) => (n < 1000 ? '<1k' : Math.round(n / 1000) + 'k')
  let { chars } = contextStats.value
  if (loading.value && liveCharsDelta.value > 0) {
    chars += liveCharsDelta.value
  }
  const tokens = currentTokenEstimate.value
  const charsStr = fmt(chars)
  const tokensStr = fmt(tokens)
  return `${charsStr} / ${tokensStr === '<1k' ? tokensStr : '~' + tokensStr}`
})
const contextStatsWarning = computed(() => {
  const provider = mode.value === 'multiagent'
    ? (multiAgentConfig.value?.overseer.provider ?? settingForm.value.api)
    : settingForm.value.api
  const providerPrefix = provider === 'official' ? 'official' : provider
  const maxKey = `${providerPrefix}MaxContextTokens` as keyof typeof settingForm.value
  const max = Number(settingForm.value[maxKey]) || 128000
  return currentTokenEstimate.value > max * 0.7
})
async function refreshContextStats() {
  try {
    contextStats.value = await fetchContextStats(threadId.value)
    liveCharsDelta.value = 0
  } catch {
    /* counter is informational — don't disrupt the user */
  }
}

// Attachment state
const MAX_TOTAL_ATTACHMENT_BYTES = 50 * 1024 * 1024 // 50 MB
const pendingAttachments = ref<{ file: File; filename: string; data: string }[]>([])
const fileInputRef = ref<HTMLInputElement>()

function openFileSelector() {
  fileInputRef.value?.click()
}

async function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return
  await addFiles(Array.from(input.files))
  input.value = '' // Reset so same file can be re-selected
}

async function addFiles(files: File[]) {
  for (const file of files) {
    const currentTotal = pendingAttachments.value.reduce((sum, a) => sum + a.file.size, 0)
    if (currentTotal + file.size > MAX_TOTAL_ATTACHMENT_BYTES) {
      messageUtil.error(t('filesTooLarge'))
      return
    }
    const data = await fileToBase64(file)
    pendingAttachments.value.push({ file, filename: file.name, data })
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      resolve(result.split(',')[1]) // Strip "data:type;base64," prefix
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function removeAttachment(index: number) {
  pendingAttachments.value.splice(index, 1)
}

function handleDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
}

async function handleDrop(e: DragEvent) {
  e.preventDefault()
  const files = e.dataTransfer?.files
  if (files?.length) {
    await addFiles(Array.from(files))
  }
}

// MultiAgent state
const multiAgentExpertCount = useStorage('multiAgentExpertCount', 2)

// Load multiagent configuration from localStorage
const loadMultiAgentConfig = (): MultiAgentConfig | null => {
  const stored = localStorage.getItem('multiAgentConfig')
  if (stored) {
    try {
      const parsed = JSON.parse(stored) as MultiAgentConfig
      // Migrate: ensure operatingMode exists
      if (!parsed.operatingMode) {
        parsed.operatingMode = 'legacy'
      }
      // Migrate: ensure exactly 4 expert slots
      while (parsed.experts.length < 4) {
        const idx = parsed.experts.length + 1
        parsed.experts.push({
          id: `expert_${idx}`,
          name: `Expert_${idx}`,
          provider: 'official',
          model: '',
          temperature: 1.0,
        })
      }
      return parsed
    } catch {
      return null
    }
  }
  return null
}

const multiAgentConfig = ref<MultiAgentConfig | null>(loadMultiAgentConfig())

// Mode stored in multiAgentConfig (single source of truth)
const multiAgentMode = computed({
  get: () => multiAgentConfig.value?.mode ?? 'parallel',
  set: (val: 'parallel' | 'collaborative') => {
    if (multiAgentConfig.value) {
      multiAgentConfig.value.mode = val
      localStorage.setItem('multiAgentConfig', JSON.stringify(multiAgentConfig.value))
    }
  },
})

const availableExpertCounts = computed(() => {
  const max = multiAgentConfig.value?.experts.filter(e => e.model?.trim()).length ?? 2
  const counts = []
  for (let i = 2; i <= Math.max(2, max); i++) counts.push(i)
  return counts
})

// Speaker color palette for multi-agent responses
const SPEAKER_COLORS: Record<string, string> = {
  Expert_1: '#3B82F6', // Blue
  Expert_2: '#10B981', // Green
  Expert_3: '#F59E0B', // Amber
  Expert_4: '#EF4444', // Red
  Expert_5: '#8B5CF6', // Purple
  Synthesizer: '#6366F1', // Indigo
  Collaborator: '#EC4899', // Pink
  Overseer: '#14B8A6', // Teal
  'Final Answer': '#6366F1', // Indigo
}

function getSpeakerColor(speaker: string | undefined): string {
  if (!speaker) return '#6B7280' // Default gray
  return SPEAKER_COLORS[speaker] || '#6B7280'
}

// Agent state - tracks which message should receive the response
const agentResponseMessageIndex = ref<number | null>(null)

// Resizable separator state
const messagesHeight = useStorage('messagesContainerHeight', 60) // Percentage
const isDragging = ref(false)
const startY = ref(0)
const startHeight = ref(0)

// Settings
const useWordFormatting = useStorage(localStorageKey.useWordFormatting, true)
const useSelectedText = useStorage(localStorageKey.useSelectedText, true)
const readOnlyMode = useStorage('readOnlyMode', false)
const insertType = ref<insertTypes>('replace')

const errorIssue = ref<boolean | string | null>(false)

const displayHistory = computed(() => {
  return history.value.filter(msg => !(msg instanceof SystemMessage))
})

type DisplayEntry =
  | { kind: 'message'; msg: Message; displayIndex: number }
  | { kind: 'tool-group'; items: { msg: ToolCallMessage; displayIndex: number }[] }

const groupedDisplayHistory = computed((): DisplayEntry[] => {
  const result: DisplayEntry[] = []
  const items = displayHistory.value
  let i = 0
  while (i < items.length) {
    if (items[i] instanceof ToolCallMessage) {
      const group: DisplayEntry & { kind: 'tool-group' } = {
        kind: 'tool-group',
        items: [{ msg: items[i] as ToolCallMessage, displayIndex: i }],
      }
      i++
      while (i < items.length && items[i] instanceof ToolCallMessage) {
        if (shouldShowBotHeader(i)) break // different bot boundary
        group.items.push({ msg: items[i] as ToolCallMessage, displayIndex: i })
        i++
      }
      result.push(group)
    } else {
      result.push({ kind: 'message', msg: items[i], displayIndex: i })
      i++
    }
  }
  return result
})

watch(loading, isLoading => {
  if (isLoading) {
    scrollToBottom()
    loadingElapsed.value = 0
    loadingTimer = setInterval(() => loadingElapsed.value++, 1000)
  } else {
    if (loadingTimer) {
      clearInterval(loadingTimer)
      loadingTimer = null
    }
  }
})


const loadingTimeDisplay = computed(() => {
  const m = Math.floor(loadingElapsed.value / 60)
  const s = loadingElapsed.value % 60
  return m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}`
})

// (Quick actions are now driven by enabledQuickActionSlots computed property)

const getCustomModels = (key: string, oldKey: string): string[] => {
  const stored = localStorage.getItem(key)
  if (stored) {
    try {
      return JSON.parse(stored)
    } catch {
      return []
    }
  }
  const oldModel = localStorage.getItem(oldKey)
  if (oldModel && oldModel.trim()) {
    return [oldModel]
  }
  return []
}

const currentModelOptions = computed(() => {
  let presetOptions: string[] = []
  let customModels: string[] = []

  switch (settingForm.value.api) {
    case 'official':
      presetOptions = settingPreset.officialModelSelect.optionList || []
      customModels = getCustomModels('customModels', 'customModel')
      break
    case 'anthropic':
      presetOptions = settingPreset.anthropicModelSelect.optionList || []
      customModels = getCustomModels('anthropicCustomModels', 'anthropicCustomModel')
      break
    case 'gemini':
      presetOptions = settingPreset.geminiModelSelect.optionList || []
      customModels = getCustomModels('geminiCustomModels', 'geminiCustomModel')
      break
    case 'ollama':
      presetOptions = settingPreset.ollamaModelSelect.optionList || []
      customModels = getCustomModels('ollamaCustomModels', 'ollamaCustomModel')
      break
    case 'groq':
      presetOptions = settingPreset.groqModelSelect.optionList || []
      customModels = getCustomModels('groqCustomModels', 'groqCustomModel')
      break
    case 'azure':
      presetOptions = settingPreset.azureModelSelect.optionList || []
      customModels = getCustomModels('azureCustomModels', 'azureDeploymentName')
      break
    case 'lmstudio':
      customModels = getCustomModels('lmstudioCustomModels', 'lmstudioCustomModel')
      break
    default:
      return []
  }

  return [...presetOptions, ...customModels]
})

const shouldShowModelSelector = computed(() => {
  const isMultiagent = mode.value === 'multiagent'
  const hasOptions = currentModelOptions.value && currentModelOptions.value.length > 0
  console.log('[HomePage] Model selector visibility check:', {
    mode: mode.value,
    isMultiagent,
    hasOptions,
    shouldShow: !isMultiagent && hasOptions,
  })
  return !isMultiagent && hasOptions
})

const currentModelSelect = computed({
  get() {
    switch (settingForm.value.api) {
      case 'official':
        return settingForm.value.officialModelSelect
      case 'anthropic':
        return settingForm.value.anthropicModelSelect
      case 'gemini':
        return settingForm.value.geminiModelSelect
      case 'ollama':
        return settingForm.value.ollamaModelSelect
      case 'groq':
        return settingForm.value.groqModelSelect
      case 'azure':
        return settingForm.value.azureModelSelect
      case 'lmstudio':
        return settingForm.value.lmstudioModelSelect
      default:
        return ''
    }
  },
  set(value) {
    switch (settingForm.value.api) {
      case 'official':
        settingForm.value.officialModelSelect = value
        localStorage.setItem(localStorageKey.model, value)
        break
      case 'anthropic':
        settingForm.value.anthropicModelSelect = value
        localStorage.setItem(localStorageKey.anthropicModel, value)
        break
      case 'gemini':
        settingForm.value.geminiModelSelect = value
        localStorage.setItem(localStorageKey.geminiModel, value)
        break
      case 'ollama':
        settingForm.value.ollamaModelSelect = value
        localStorage.setItem(localStorageKey.ollamaModel, value)
        break
      case 'groq':
        settingForm.value.groqModelSelect = value
        localStorage.setItem(localStorageKey.groqModel, value)
        break
      case 'azure':
        settingForm.value.azureModelSelect = value
        localStorage.setItem(localStorageKey.azureModel, value)
        break
      case 'lmstudio':
        settingForm.value.lmstudioModelSelect = value
        localStorage.setItem(localStorageKey.lmstudioModel, value)
        break
    }
  },
})

function settings() {
  // FIXME: 使用路由方式会改变当前的threadID,进而重置页面
  router.push('/settings')
}

function checkPoints() {
  showCheckpoints.value = true
}

async function startNewChat() {
  if (loading.value) {
    stopGeneration()
  }
  userInput.value = ''
  history.value = []
  messageMetadata.clear()
  messageAttachmentsMap.clear()
  currentBotMessageIndex.value = null
  agentResponseMessageIndex.value = null
  threadId.value = uuidv4()
  customSystemPrompt.value = ''
  contextStats.value = { chars: 0, tokens: 0 }
  liveCharsDelta.value = 0

  console.log('[HomePage] New chat started, thread:', threadId.value)

  await nextTick()
  adjustTextareaHeight()
}

function stopGeneration() {
  if (abortController.value) {
    abortController.value.abort()
    abortController.value = null
  }
  loading.value = false
}

function adjustTextareaHeight() {}

async function scrollToBottom() {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

// Resizable separator drag handlers
function startDrag(e: MouseEvent | TouchEvent) {
  isDragging.value = true
  const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY
  startY.value = clientY
  startHeight.value = messagesHeight.value

  // Add event listeners
  if ('touches' in e) {
    document.addEventListener('touchmove', onDrag)
    document.addEventListener('touchend', stopDrag)
  } else {
    document.addEventListener('mousemove', onDrag)
    document.addEventListener('mouseup', stopDrag)
  }

  // Prevent text selection during drag
  e.preventDefault()
}

function onDrag(e: MouseEvent | TouchEvent) {
  if (!isDragging.value) return

  const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY
  const container = messagesContainer.value?.$el || messagesContainer.value
  if (!container) return

  // Get container dimensions
  const containerRect = container.parentElement?.getBoundingClientRect()
  if (!containerRect) return

  // Calculate delta and new height percentage
  const deltaY = clientY - startY.value
  const deltaPercent = (deltaY / containerRect.height) * 100
  const newHeight = startHeight.value + deltaPercent

  // Apply constraints (min 15%, max 85%)
  messagesHeight.value = Math.max(15, Math.min(85, newHeight))
}

function stopDrag() {
  isDragging.value = false

  // Remove event listeners
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
  document.removeEventListener('touchmove', onDrag)
  document.removeEventListener('touchend', stopDrag)
}

async function sendMessage() {
  if (!userInput.value.trim() || loading.value) return
  if (!checkApiKey()) return

  const userMessage = userInput.value.trim()
  userInput.value = ''

  // Capture attachments for this message and clear pending list
  const messageAttachments = pendingAttachments.value.map(a => ({ filename: a.filename, data: a.data }))
  pendingAttachments.value = []

  await nextTick()
  adjustTextareaHeight()

  // Get selected text from Word (clean: tracked-change deletions stripped)
  let selectedText = ''
  if (useSelectedText.value) {
    try {
      selectedText = await getCleanSelectedText()
    } catch (error) {
      console.warn('Could not read selection:', error)
    }
  }

  // Add user message
  const fullMessage = new HumanMessage(
    selectedText ? `${userMessage}\n\n[Selected text: "${selectedText}"]` : userMessage,
  )

  // Track attachment filenames for this user message (will be at current history length after processChat pushes it)
  if (messageAttachments.length > 0) {
    const userMsgIndex = history.value.length // processChat will push user msg at this index
    messageAttachmentsMap.set(
      userMsgIndex,
      messageAttachments.map(a => ({ filename: a.filename })),
    )
  }

  scrollToBottom()

  loading.value = true
  abortController.value = new AbortController()

  try {
    await processChat(fullMessage, undefined, messageAttachments)
  } catch (error: any) {
    if (error.name === 'AbortError') {
      messageUtil.info(t('generationStop'))
      await saveConversationToThread()
      refreshContextStats()
    } else {
      console.error(error)
      messageUtil.error(t('failedToResponse'))
      await cleanupFailedResponseAndSave()
    }
  } finally {
    loading.value = false
    abortController.value = null
    liveCharsDelta.value = 0
  }
}

async function processChat(
  userMessage: HumanMessage,
  systemMessage?: string,
  attachments?: { filename: string; data: string }[],
) {
  const settings = settingForm.value
  const { replyLanguage: lang, api: provider } = settings

  const isAgentMode = mode.value === 'agent'
  const isMultiAgentMode = mode.value === 'multiagent'

  // Reset streaming index trackers for new request
  agentResponseMessageIndex.value = null
  currentBotMessageIndex.value = null

  // Seed live token estimate with user message length
  const userMsgLength = getMessageText(userMessage).length
  liveCharsDelta.value = userMsgLength

  // Determine if we should send custom system prompt or let backend generate default
  const hasCustomPrompt = !!(customSystemPrompt.value || systemMessage)

  // Add user message to GUI history (display-only — backend manages its own history)
  history.value.push(userMessage)

  // All modes: send only the new user message (+ system message if custom prompt).
  // Backend ConversationStore handles cross-mode consigliere history.
  let finalMessages: any[]
  let languageParam: string | undefined

  if (hasCustomPrompt) {
    let systemContent = customSystemPrompt.value || systemMessage || ''
    if (additionalSystemPrompt.value) {
      systemContent = '# Behavior\n' + additionalSystemPrompt.value + '\n\n' + systemContent
    }
    finalMessages = [new SystemMessage(systemContent), userMessage]
    languageParam = undefined // Don't send language, backend uses custom prompt
  } else {
    finalMessages = [userMessage]
    languageParam = lang // Backend will generate prompt for this language
  }
  // Build provider configuration
  const providerConfigs: Record<string, any> = {
    official: {
      provider: 'official',
      config: {
        apiKey: settings.officialAPIKey,
        baseURL: settings.officialBasePath,
        dangerouslyAllowBrowser: true,
      },
      maxContextTokens: settings.officialMaxContextTokens,
      temperature: settings.officialTemperature,
      model: settings.officialModelSelect,
    },
    anthropic: {
      provider: 'anthropic',
      anthropicAPIKey: settings.anthropicAPIKey,
      anthropicModel: settings.anthropicModelSelect,
      temperature: settings.anthropicTemperature,
      maxContextTokens: settings.anthropicMaxContextTokens,
    },
    groq: {
      provider: 'groq',
      groqAPIKey: settings.groqAPIKey,
      groqModel: settings.groqModelSelect,
      maxContextTokens: settings.groqMaxContextTokens,
      temperature: settings.groqTemperature,
    },
    azure: {
      provider: 'azure',
      azureAPIKey: settings.azureAPIKey,
      azureAPIEndpoint: settings.azureAPIEndpoint,
      azureDeploymentName: settings.azureModelSelect,
      azureAPIVersion: settings.azureAPIVersion,
      maxContextTokens: settings.azureMaxContextTokens,
      temperature: settings.azureTemperature,
    },
    gemini: {
      provider: 'gemini',
      geminiAPIKey: settings.geminiAPIKey,
      maxContextTokens: settings.geminiMaxContextTokens,
      temperature: settings.geminiTemperature,
      geminiModel: settings.geminiModelSelect,
    },
    ollama: {
      provider: 'ollama',
      ollamaEndpoint: settings.ollamaEndpoint,
      ollamaModel: settings.ollamaModelSelect,
      temperature: settings.ollamaTemperature,
      maxContextTokens: settings.ollamaMaxContextTokens,
    },
    lmstudio: {
      provider: 'lmstudio',
      lmstudioEndpoint: settings.lmstudioEndpoint,
      lmstudioFilterThinking: settings.lmstudioFilterThinking,
      lmstudioModel: (settings.lmstudioModelSelect as string) || undefined,
      temperature: settings.lmstudioTemperature,
      maxContextTokens: settings.lmstudioMaxContextTokens,
    },
  }

  const currentConfig = providerConfigs[provider]
  if (!currentConfig) {
    messageUtil.error(t('notSupportedProvider'))
    return
  }

  // Validate that a model is selected (lmstudio auto-detects its model)
  if (!currentModelSelect.value && provider !== 'lmstudio') {
    messageUtil.error('No model selected. Please select a model in Settings.')
    loading.value = false
    history.value.pop() // Remove the user message we just added
    return
  }

  // For agent mode, don't create response message yet (tool calls come first)
  // For multiagent mode, callbacks create their own messages
  // For ask mode, create empty message now (response writes into it)
  if (!isAgentMode && !isMultiAgentMode) {
    history.value.push(new AIMessage(''))
  }

  // Helper function to build provider config for multiagent roles
  const buildProviderConfigForRole = (provider: string, model: string): MultiAgentExpertConfig => {
    const baseConfig = providerConfigs[provider]
    if (!baseConfig) {
      throw new Error(`Unsupported provider: ${provider}`)
    }

    // Clone the config and update the model field
    const config = { ...baseConfig }

    // Update model based on provider type
    if (provider === 'official') {
      config.model = model
    } else if (provider === 'anthropic') {
      config.anthropicModel = model
    } else if (provider === 'gemini') {
      config.geminiModel = model
    } else if (provider === 'groq') {
      config.groqModel = model
    } else if (provider === 'ollama') {
      config.ollamaModel = model
    } else if (provider === 'azure') {
      config.azureDeploymentName = model
    } else if (provider === 'lmstudio') {
      config.lmstudioModel = model
    }

    return config
  }

  // Use multiagent mode if enabled
  if (isMultiAgentMode) {
    // Validate that multiagent configuration exists
    const config = multiAgentConfig.value
    if (!config) {
      messageUtil.error('Multi-agent configuration not found. Please configure models in Settings → Multi-Agent.')
      loading.value = false
      history.value.pop() // Remove the user message we just added
      return
    }

    // Use the dropdown selection, capped by how many experts are actually configured
    const expertCount = Math.min(multiAgentExpertCount.value, config.experts.length)

    // Validate that selected experts have models configured
    for (let i = 0; i < expertCount; i++) {
      const expert = config.experts[i]
      if (!expert.model || expert.model.trim() === '') {
        messageUtil.error(
          `Expert ${i + 1} (${expert.name}) has no model configured. Please set models in Settings → Multi-Agent.`,
        )
        loading.value = false
        history.value.pop()
        return
      }
    }

    // Validate overseer has model configured
    if (!config.overseer.model || config.overseer.model.trim() === '') {
      messageUtil.error('Overseer has no model configured. Please set models in Settings → Multi-Agent.')
      loading.value = false
      history.value.pop()
      return
    }

    // Build expert configs from multiAgentConfig (only the selected count)
    const experts: MultiAgentExpertConfig[] = []

    for (let i = 0; i < expertCount; i++) {
      const expert = config.experts[i]
      experts.push(buildProviderConfigForRole(expert.provider, expert.model))
    }

    // Build overseer and synthesizer configs (use overseer for both)
    const overseerConfig = buildProviderConfigForRole(config.overseer.provider, config.overseer.model)
    const synthesizerConfig = buildProviderConfigForRole(config.overseer.provider, config.overseer.model)

    // Build formatter config if configured (legacy mode only)
    const formatterConfig = config.formatter?.model?.trim()
      ? buildProviderConfigForRole(config.formatter.provider, config.formatter.model)
      : undefined

    await getMultiAgentResponse({
      mode: multiAgentMode.value,
      operatingMode: multiAgentConfig.value?.operatingMode ?? 'legacy',
      maxRounds: multiAgentConfig.value?.maxRounds ?? 3,
      useExpertMemory: true,
      expertFullHistory: multiAgentConfig.value?.expertFullHistory ?? false,
      useExpertParallelization: multiAgentConfig.value?.useExpertParallelization ?? true,
      experts,
      overseer: overseerConfig,
      synthesizer: synthesizerConfig,
      formatter: formatterConfig,
      recursionLimit: settings.agentMaxIterations,
      llmTimeout: settings.llmTimeout,
      language: languageParam,
      additionalSystemPrompt: additionalSystemPrompt.value || undefined,
      enabledWordTools: getActiveWordToolNames(),
      enabledGeneralTools: enabledGeneralTools.value,
      messages: finalMessages,
      errorIssue,
      loading,
      abortSignal: abortController.value?.signal,
      threadId: threadId.value,
      conversationId: threadId.value,
      attachments,
      attachmentCharLimit: settings.attachmentCharLimit,
      onStream: (text: string, speaker?: string) => {
        if (!speaker) throw new Error('[MultiAgent] BUG: Received stream event without speaker identity')
        console.error('[MultiAgent] Unexpected text event - multiagent should only emit message events')
        const newMsg = new AIMessage(text)
        history.value.push(newMsg)
        currentBotMessageIndex.value = history.value.length - 1
        const botType = speaker === 'Synthesizer' ? 'synthesizer' : speaker === 'Overseer' ? 'overseer' : 'expert'
        const emoji = botType === 'synthesizer' ? '🔮' : botType === 'overseer' ? '🎯' : '👤'
        messageMetadata.set(currentBotMessageIndex.value, { botType, botName: speaker, emoji })
        scrollToBottom()
      },
      onMessage: (content: string, speaker?: string, round?: number) => {
        if (!speaker) throw new Error('[MultiAgent] BUG: Received message without speaker identity')
        const newMsg = new AIMessage(content)
        history.value.push(newMsg)
        currentBotMessageIndex.value = history.value.length - 1
        const botType = speaker === 'Synthesizer' ? 'synthesizer' : speaker === 'Overseer' ? 'overseer' : 'expert'
        const emoji = botType === 'synthesizer' ? '🔮' : botType === 'overseer' ? '🎯' : '👤'
        messageMetadata.set(currentBotMessageIndex.value, {
          botType,
          botName: speaker,
          emoji,
          roundNumber: round,
        })
        liveCharsDelta.value += content.length
        scrollToBottom()
      },
      onToolCall: (toolName: string, _args: any, speaker?: string) => {
        if (!speaker) throw new Error('[MultiAgent] BUG: Received tool_call without speaker identity')
        const msg = new ToolCallMessage(toolName)
        history.value.push(msg)
        const botType = speaker === 'Synthesizer' ? 'synthesizer' : speaker === 'Overseer' ? 'overseer' : 'expert'
        messageMetadata.set(history.value.length - 1, {
          botType,
          botName: speaker,
          emoji: botType === 'synthesizer' ? '🔮' : botType === 'overseer' ? '🎯' : '👤',
        })
        liveCharsDelta.value += toolName.length + 20
        scrollToBottom()
      },
      onToolResult: (_toolName: string, _result: string, _speaker?: string) => {
        // No-op: tool completion is implicit
      },
      onOverseerDecision: (decision: string) => {
        const decisionText = `**Decision: ${decision} discussion**`
        const decisionMsg = new AIMessage(decisionText)
        history.value.push(decisionMsg)
        messageMetadata.set(history.value.length - 1, {
          botType: 'overseer',
          botName: 'Overseer',
          emoji: '🎯',
          isDecisionOnly: true,
        })
        currentBotMessageIndex.value = null
        scrollToBottom()
      },
    })
  } else if (isAgentMode) {
    const tools = getActiveTools()

    await getAgentResponse(
      {
        ...currentConfig,
        recursionLimit: settings.agentMaxIterations,
        llmTimeout: settings.llmTimeout,
        additionalSystemPrompt: additionalSystemPrompt.value || undefined,
        messages: finalMessages,
        tools,
        errorIssue,
        loading,
        abortSignal: abortController.value?.signal,
        threadId: threadId.value,
        conversationId: threadId.value,
        checkpointId: currentCheckpointId.value,
        attachments,
        attachmentCharLimit: settings.attachmentCharLimit,
        onStream: (text: string) => {
          console.log('[HomePage] onStream received:', text.length, 'chars')
          console.log('[HomePage] Preview:', text.substring(0, 50))

          // Create response message on first stream (after tool calls have been added)
          if (agentResponseMessageIndex.value === null) {
            history.value.push(new AIMessage(text))
            agentResponseMessageIndex.value = history.value.length - 1
          } else {
            // Update existing response message
            history.value[agentResponseMessageIndex.value] = new AIMessage(text)
          }

          liveCharsDelta.value = userMsgLength + text.length
          scrollToBottom()
        },
        onToolCall: (toolName: string, _args: any) => {
          history.value.push(new ToolCallMessage(toolName))
          agentResponseMessageIndex.value = null // Next text creates a new bubble
          liveCharsDelta.value += toolName.length + 20
          scrollToBottom()
        },
        onToolResult: (_toolName: string, _result: string) => {
          // No-op: tool completion is implicit, no need to show separate completion message
        },
        onNewBlock: () => {
          agentResponseMessageIndex.value = null
        },
      },
      languageParam,
    )
  } else {
    await getChatResponse(
      {
        ...currentConfig,
        llmTimeout: settings.llmTimeout,
        additionalSystemPrompt: additionalSystemPrompt.value || undefined,
        messages: finalMessages,
        errorIssue,
        loading,
        abortSignal: abortController.value?.signal,
        threadId: threadId.value,
        conversationId: threadId.value,
        attachments,
        attachmentCharLimit: settings.attachmentCharLimit,
        onStream: (text: string) => {
          console.log('[HomePage] onStream received:', text.length, 'chars')
          console.log('[HomePage] Preview:', text.substring(0, 50))
          const lastIndex = history.value.length - 1
          history.value[lastIndex] = new AIMessage(text)
          liveCharsDelta.value = userMsgLength + text.length
          scrollToBottom()
        },
      },
      languageParam,
    )
  }

  if (errorIssue.value) {
    if (typeof errorIssue.value === 'string') {
      messageUtil.error(t(errorIssue.value))
    } else {
      messageUtil.error(t('somethingWentWrong'))
    }
    errorIssue.value = null
    await cleanupFailedResponseAndSave()
    return
  }

  await saveConversationToThread()
  refreshContextStats()

  scrollToBottom()
}

async function insertToDocument(content: string, type: insertTypes) {
  insertType.value = type

  if (useWordFormatting.value) {
    await insertFormattedResult(content, insertType)
  } else {
    insertResult(content, insertType)
  }
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text)
  messageUtil.success(t('copied'))
}

// ---------------------------------------------------------------------------
// Edit / Fork / Retry helpers
// ---------------------------------------------------------------------------

/** Count how many HumanMessages appear from index 0 to historyIndex (inclusive) → 1-indexed backend turn. */
function getTurnForHumanMessageIndex(historyIndex: number): number {
  let turnCount = 0
  for (let i = 0; i <= historyIndex; i++) {
    if (history.value[i] instanceof HumanMessage) turnCount++
  }
  if (turnCount === 0) throw new Error(`No HumanMessage at or before index ${historyIndex}`)
  return turnCount
}

function isLastHumanMessage(index: number): boolean {
  for (let i = history.value.length - 1; i >= 0; i--) {
    if (history.value[i] instanceof HumanMessage) return i === index
  }
  return false
}

/** Truncate frontend history + metadata/attachments maps from a given index onward. */
function truncateHistoryAndMaps(fromIndex: number) {
  history.value = history.value.slice(0, fromIndex)
  for (const key of [...messageMetadata.keys()]) {
    if (key >= fromIndex) messageMetadata.delete(key)
  }
  for (const key of [...messageAttachmentsMap.keys()]) {
    if (key >= fromIndex) messageAttachmentsMap.delete(key)
  }
}

/** Remove partial AI/tool responses after the last user message and persist thread. */
async function cleanupFailedResponseAndSave() {
  for (let i = history.value.length - 1; i >= 0; i--) {
    if (history.value[i] instanceof HumanMessage) {
      truncateHistoryAndMaps(i + 1)
      break
    }
  }
  await saveConversationToThread()
}

function resizeEditTextarea(el: HTMLTextAreaElement) {
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 'px'
}

async function startEdit(index: number) {
  if (loading.value) return
  editingMessageIndex.value = index
  editText.value = getMessageText(history.value[index])
  await nextTick()
  if (editTextareaEl) resizeEditTextarea(editTextareaEl)
}

function cancelEdit() {
  editingMessageIndex.value = null
  editText.value = ''
}

async function submitEdit() {
  const editedText = editText.value.trim()
  if (!editedText || loading.value) return
  const index = editingMessageIndex.value
  if (index === null) return

  const turn = getTurnForHumanMessageIndex(index)

  try {
    // Update backend ConversationStore entry in-place
    await editConversationMessage(threadId.value, turn, editedText)
  } catch (error) {
    console.error('[HomePage] Failed to edit message:', error)
    messageUtil.error(String(error))
    return
  }

  // Update frontend history in-place — all other messages remain
  history.value[index] = new HumanMessage(editedText)
  cancelEdit()

  // Persist the updated thread
  await saveConversationToThread()
  refreshContextStats()
}

async function forkFromMessage(index: number) {
  if (loading.value) return

  const turn = getTurnForHumanMessageIndex(index)
  const newThreadId = uuidv4()

  try {
    await forkConversation(threadId.value, newThreadId, turn)
  } catch (error) {
    console.error('[HomePage] Failed to fork conversation:', error)
    messageUtil.error(String(error))
    return
  }

  // Include history up to and including the user message only (cut AI responses after it)
  const forkedHistory = history.value.slice(0, index + 1)
  const forkedMetadata = new Map<number, BotMetadata>()
  const forkedAttachments = new Map<number, { filename: string }[]>()
  for (let i = 0; i <= index; i++) {
    if (messageMetadata.has(i)) forkedMetadata.set(i, messageMetadata.get(i)!)
    if (messageAttachmentsMap.has(i)) forkedAttachments.set(i, messageAttachmentsMap.get(i)!)
  }

  history.value = forkedHistory
  messageMetadata.clear()
  messageAttachmentsMap.clear()
  forkedMetadata.forEach((v, k) => messageMetadata.set(k, v))
  forkedAttachments.forEach((v, k) => messageAttachmentsMap.set(k, v))
  threadId.value = newThreadId

  await saveConversationToThread()
  refreshContextStats()
  messageUtil.success(t('fork'))
  console.log('[HomePage] Forked conversation to new thread:', newThreadId)
}

async function retryLastMessage() {
  if (loading.value) return

  let lastHumanIndex = -1
  for (let i = history.value.length - 1; i >= 0; i--) {
    if (history.value[i] instanceof HumanMessage) {
      lastHumanIndex = i
      break
    }
  }
  if (lastHumanIndex === -1) return

  const turn = getTurnForHumanMessageIndex(lastHumanIndex)
  const originalText = getMessageText(history.value[lastHumanIndex])

  try {
    await truncateConversation(threadId.value, turn)
  } catch (error) {
    console.error('[HomePage] Failed to truncate conversation for retry:', error)
    messageUtil.error(String(error))
    return
  }

  truncateHistoryAndMaps(lastHumanIndex)

  const userMessage = new HumanMessage(originalText)
  loading.value = true
  abortController.value = new AbortController()
  try {
    await processChat(userMessage)
  } catch (error: any) {
    if (error.name === 'AbortError') {
      messageUtil.info(t('generationStop'))
      await saveConversationToThread()
      refreshContextStats()
    } else {
      console.error(error)
      messageUtil.error(t('failedToResponse'))
      await cleanupFailedResponseAndSave()
    }
  } finally {
    loading.value = false
    abortController.value = null
    liveCharsDelta.value = 0
  }
}

// Auto-cancel edit mode if loading starts from elsewhere
watch(loading, val => {
  if (val && editingMessageIndex.value !== null) cancelEdit()
})

function checkApiKey() {
  const auth = {
    type: settingForm.value.api as supportedPlatforms,
    apiKey: settingForm.value.officialAPIKey,
    azureAPIKey: settingForm.value.azureAPIKey,
    geminiAPIKey: settingForm.value.geminiAPIKey,
    groqAPIKey: settingForm.value.groqAPIKey,
    anthropicAPIKey: settingForm.value.anthropicAPIKey,
  }
  if (!checkAuth(auth)) {
    messageUtil.error(t('noAPIKey'))
    return false
  }
  return true
}

const THINK_TAG = '<think>'
const THINK_TAG_END = '</think>'

interface RenderSegment {
  type: 'text' | 'think'
  text: string
}

const flattenContentArray = (content: any[]): string =>
  content
    .map((part: any) => {
      if (typeof part === 'string') return part
      if (part?.text && typeof part.text === 'string') return part.text
      if (part?.data && typeof part.data === 'string') return part.data
      return ''
    })
    .join('')

const getMessageText = (msg: Message): string => {
  const content: any = (msg as any).content
  if (typeof content === 'string') return content
  if (Array.isArray(content)) return flattenContentArray(content)
  return ''
}

const cleanMessageText = (msg: Message): string => {
  let raw = getMessageText(msg)
  // Remove standard <think>...</think> blocks
  raw = raw.replace(new RegExp(`${THINK_TAG}[\\s\\S]*?${THINK_TAG_END}`, 'g'), '')
  // Remove orphan content ending with </think> at start (no preceding <think>)
  raw = raw.replace(new RegExp(`^[\\s\\S]*?${THINK_TAG_END}`, ''), '')
  return raw.trim()
}

const splitThinkSegments = (text: string): RenderSegment[] => {
  if (!text) return []

  const segments: RenderSegment[] = []
  let cursor = 0

  while (cursor < text.length) {
    const start = text.indexOf(THINK_TAG, cursor)
    if (start === -1) {
      segments.push({ type: 'text', text: text.slice(cursor) })
      break
    }

    if (start > cursor) {
      segments.push({ type: 'text', text: text.slice(cursor, start) })
    }

    const end = text.indexOf(THINK_TAG_END, start + THINK_TAG.length)
    if (end === -1) {
      segments.push({
        type: 'think',
        text: text.slice(start + THINK_TAG.length),
      })
      break
    }

    segments.push({
      type: 'think',
      text: text.slice(start + THINK_TAG.length, end),
    })
    cursor = end + THINK_TAG_END.length
  }

  return segments.filter(segment => segment.text)
}

const renderSegments = (msg: Message): RenderSegment[] => {
  const raw = getMessageText(msg)
  const segments = splitThinkSegments(raw)
  // When filter_thinking is ON (default), hide thinking segments from display.
  // When OFF, show them in collapsible <details> sections.
  if (settingForm.value.lmstudioFilterThinking) {
    return segments.filter(s => s.type === 'text')
  }
  return segments
}

// Bot metadata helpers for multiagent display
const getBotMetadata = (index: number): BotMetadata | undefined => {
  return messageMetadata.get(index)
}

const shouldShowBotHeader = (index: number): boolean => {
  const meta = getBotMetadata(index)
  if (!meta || meta.isDecisionOnly) return false

  // Scan backward through all messages in this turn/round
  for (let i = index - 1; i >= 0; i--) {
    const prevMsg = displayHistory.value[i]
    if (prevMsg instanceof HumanMessage) return true // Turn boundary — show header

    const prevMeta = getBotMetadata(i)
    if (!prevMeta) continue
    if (prevMeta.isDecisionOnly) return true // Round boundary — show header

    if (prevMeta.botName === meta.botName) {
      return false // Same bot already has a header in this turn/round
    }
    // Different bot — keep scanning backward (don't stop here)
  }
  return true
}

const getMessageAttachments = (index: number): { filename: string }[] | undefined => {
  return messageAttachmentsMap.get(index)
}

const getBotStyles = (botType: string, botName?: string) => {
  // Expert color assignment based on bot name
  if (botType === 'expert' && botName) {
    // Extract expert number from botName (e.g., "Expert_1" -> 1)
    const expertMatch = botName.match(/Expert_(\d+)/)
    const expertNum = expertMatch ? parseInt(expertMatch[1], 10) : 1

    // Define 5 distinct expert colors (cycle if more than 5 experts)
    const expertColors = [
      {
        // Expert 1: Orange
        header: 'bg-orange-500/10 text-orange-600 dark:text-orange-400 border border-orange-500/20',
        bubble: 'border-orange-500/30 bg-orange-500/5',
      },
      {
        // Expert 2: Cyan
        header: 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20',
        bubble: 'border-cyan-500/30 bg-cyan-500/5',
      },
      {
        // Expert 3: Pink
        header: 'bg-pink-500/10 text-pink-600 dark:text-pink-400 border border-pink-500/20',
        bubble: 'border-pink-500/30 bg-pink-500/5',
      },
      {
        // Expert 4: Amber
        header: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20',
        bubble: 'border-amber-500/30 bg-amber-500/5',
      },
      {
        // Expert 5: Indigo
        header: 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20',
        bubble: 'border-indigo-500/30 bg-indigo-500/5',
      },
    ]

    const colorIndex = (expertNum - 1) % expertColors.length
    return expertColors[colorIndex]
  }

  // Consigliere styling: overseer, synthesizer, and fallback all use neutral grey
  // (only experts get distinct colors — consigliere is one persistent persona)
  const consigliereStyle = {
    header: 'bg-bg-secondary text-secondary border border-border-secondary',
    bubble: 'border-border-secondary bg-bg-tertiary',
  }

  if (botType === 'overseer' || botType === 'synthesizer') {
    return consigliereStyle
  }

  return consigliereStyle
}

const addWatch = () => {
  watch(
    () => settingForm.value.replyLanguage,
    () => {
      localStorage.setItem(localStorageKey.replyLanguage, settingForm.value.replyLanguage)
    },
  )
  watch(
    () => settingForm.value.api,
    () => {
      localStorage.setItem(localStorageKey.api, settingForm.value.api)
    },
  )
}

async function initData() {
  insertType.value = (localStorage.getItem(localStorageKey.insertType) as insertTypes) || 'replace'
}

async function handleRestore(checkpointId: string) {
  currentCheckpointId.value = checkpointId
  showCheckpoints.value = false

  // Fetch the history up to the selected checkpoint
  const checkpointTuple = await saver.getTuple({
    configurable: { thread_id: threadId.value, checkpoint_id: checkpointId },
  })

  if (checkpointTuple) {
    const messages = checkpointTuple.checkpoint.channel_values.messages
    if (messages && Array.isArray(messages)) {
      history.value = messages
        .filter((msg: any) => ['human', 'ai'].includes(msg.type))
        .map((msg: any) => {
          return msg.type === 'human' ? new HumanMessage(msg.content) : new AIMessage(msg.content)
        })
    }
  }
}

async function getThreadCreatedAt(targetThreadId: string): Promise<string> {
  const existing = await fetchThread(targetThreadId)
  return existing?.createdAt || new Date().toISOString()
}

function generateThreadTitle(messages: SerializedMessage[]): string {
  const firstUserMsg = messages.find(m => m.role === 'user')
  if (!firstUserMsg) {
    return t('newConversation')
  }

  let title = firstUserMsg.content.trim()
  title = title.replace(/^(please|can you|could you|help me|i need|i want)\s+/i, '')

  const firstSentence = title.split(/[.!?]/)[0]
  title = firstSentence.slice(0, 50)

  if (firstSentence.length > 50 || title !== firstUserMsg.content.trim()) {
    title += '...'
  }

  return title
}

async function saveConversationToThread() {
  if (!threadId.value || history.value.length === 0) {
    return
  }

  try {
    const serializedMessages: SerializedMessage[] = []
    for (let i = 0; i < history.value.length; i++) {
      const msg = history.value[i]
      const content = getMessageText(msg)
      if (!content || content.trim().length === 0) continue

      const attachments = messageAttachmentsMap.get(i)
      if (msg instanceof ToolCallMessage) {
        serializedMessages.push({
          role: 'tool_call' as const,
          content: msg.content,
          timestamp: Date.now(),
          metadata: messageMetadata.get(i),
          toolName: msg.toolName,
          attachments,
        })
      } else {
        serializedMessages.push({
          role: msg._getType() === 'human' ? 'user' : msg._getType() === 'ai' ? 'assistant' : 'system',
          content: getMessageText(msg),
          timestamp: Date.now(),
          metadata: messageMetadata.get(i),
          attachments,
        })
      }
    }

    const title = generateThreadTitle(serializedMessages)

    const thread: BackendThread = {
      id: threadId.value,
      title,
      createdAt: await getThreadCreatedAt(threadId.value),
      updatedAt: new Date().toISOString(),
      messages: serializedMessages,
      mode: mode.value,
      provider: settingForm.value.api,
      model: currentModelSelect.value,
      messageCount: serializedMessages.length,
    }

    await saveThreadToBackend(thread)
    console.log('[HomePage] Conversation saved to thread:', threadId.value)
  } catch (error) {
    console.error('[HomePage] CRITICAL: Failed to save conversation:', error)
    messageUtil.error(t('failedToSaveHistory'))
    throw error
  }
}

async function loadThreadHistory(targetThreadId: string) {
  try {
    const thread = await fetchThread(targetThreadId)

    if (!thread || !thread.messages || thread.messages.length === 0) {
      console.log('[HomePage] No history found for thread:', targetThreadId)
      history.value = []
      messageMetadata.clear()
      messageAttachmentsMap.clear()
      currentCheckpointId.value = ''
      contextStats.value = { chars: 0, tokens: 0 }
      liveCharsDelta.value = 0
      return
    }

    history.value = thread.messages.map((msg: any) => {
      if (msg.role === 'user') {
        return new HumanMessage(msg.content)
      } else if (msg.role === 'assistant') {
        return new AIMessage(msg.content)
      } else if (msg.role === 'tool_call' && msg.toolName) {
        return new ToolCallMessage(msg.toolName)
      } else {
        return new SystemMessage(msg.content)
      }
    })

    messageMetadata.clear()
    messageAttachmentsMap.clear()
    thread.messages.forEach((msg: any, index: number) => {
      if (msg.metadata) {
        messageMetadata.set(index, msg.metadata)
      }
      if (msg.attachments?.length) {
        messageAttachmentsMap.set(index, msg.attachments)
      }
    })

    if (thread.mode) {
      mode.value = thread.mode as 'ask' | 'agent' | 'multiagent'
    }

    console.log('[HomePage] Loaded thread history:', {
      threadId: targetThreadId,
      messageCount: thread.messages.length,
      mode: thread.mode,
    })

    await scrollToBottom()
    refreshContextStats()
  } catch (error) {
    console.error('[HomePage] CRITICAL: Failed to load thread history:', error)
    messageUtil.error(t('failedToLoadHistory'))
    throw error
  }
}

async function handleSelectThread(newThreadId: string) {
  threadId.value = newThreadId
  showCheckpoints.value = false
  await loadThreadHistory(newThreadId)
}

onBeforeMount(async () => {
  addWatch()
  initData()
  resolveActiveSystemPrompt()

  // Sync history DB path with backend if user has configured one
  const storedDbPath = localStorage.getItem(localStorageKey.historyDbPath)
  if (storedDbPath) {
    try {
      await setHistoryPath(storedDbPath)
    } catch (e) {
      console.warn('[HomePage] Failed to sync history DB path with backend:', e)
    }
  }

  // Watch for multiAgentConfig changes in localStorage
  window.addEventListener('storage', e => {
    if (e.key === 'multiAgentConfig' && e.newValue) {
      try {
        multiAgentConfig.value = JSON.parse(e.newValue)
      } catch (error) {
        console.error('Failed to parse multiAgentConfig from storage:', error)
      }
    }
  })

  if (threadId.value) {
    loading.value = true
    try {
      await loadThreadHistory(threadId.value)
    } catch (e) {
      console.error('Auto reload history failed:', e)
    } finally {
      loading.value = false
    }
  }
})
</script>

<style scoped>
.separator-handle {
  touch-action: none;
  user-select: none;
}

.separator-active {
  opacity: 0.8;
}

.separator-handle:hover {
  background-color: rgba(var(--accent-rgb), 0.1);
}

.tool-call-bubble {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  width: fit-content;
}

.tool-icon {
  font-size: 0.8rem;
}

.tool-name {
  font-weight: 500;
}
</style>
