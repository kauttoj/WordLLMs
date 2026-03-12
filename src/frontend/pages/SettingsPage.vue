<template>
  <div class="relative flex h-full w-full items-center justify-center bg-bg-secondary">
    <!-- Header with back button -->
    <div class="relative z-1 flex h-full w-full flex-col items-center justify-start gap-2 rounded-xl border-none p-2">
      <div
        class="flex w-full items-center justify-between gap-1 overflow-visible rounded-2xl border border-border-secondary p-0 shadow-sm"
      >
        <div class="flex flex-wrap items-center gap-4 p-1">
          <CustomButton
            :icon="ArrowLeft"
            type="secondary"
            class="border-none p-1!"
            text=""
            :title="t('back')"
            @click="backToHome"
          />
        </div>
        <div class="flex-1">
          <h2 class="text-sm font-semibold text-main">
            {{ $t('settings') || 'Settings' }}
          </h2>
        </div>
      </div>

      <!-- Tab Navigation -->
      <div class="flex w-full justify-between rounded-2xl border border-border-secondary p-0">
        <CustomButton
          v-for="tab in tabs"
          :key="tab.id"
          text=""
          :type="currentTab === tab.id ? 'primary' : 'secondary'"
          :title="$t(tab.label) || tab.defaultLabel"
          :icon="tab.icon"
          :icon-size="16"
          class="flex-1 rounded-sm border-none! p-1!"
          @click="currentTab = tab.id"
        />
      </div>

      <!-- Main Content -->
      <div class="w-full flex-1 overflow-hidden">
        <div class="h-full w-full overflow-auto rounded-md shadow-md">
          <!-- General Settings -->
          <div
            v-show="currentTab === 'general'"
            class="flex h-full w-full flex-col items-center gap-2 bg-bg-secondary p-1"
          >
            <SettingCard v-if="optionLists.localLanguageList.length > 1">
              <SingleSelect
                v-model="settingForm.localLanguage"
                :tight="false"
                :key-list="settingPreset.localLanguage.optionObj.map(item => item.value)"
                :title="$t('localLanguageLabel')"
                :fronticon="false"
                :placeholder="
                  settingPreset.localLanguage.optionObj.find(option => option.value === settingForm.localLanguage)
                    ?.label || settingForm.localLanguage
                "
              >
                <template #item="{ item }">
                  {{ settingPreset.localLanguage.optionObj.find(option => option.value === item)?.label || item }}
                </template>
              </SingleSelect>
            </SettingCard>

            <SettingCard>
              <SingleSelect
                v-model="settingForm.replyLanguage"
                :tight="false"
                :key-list="settingPreset.replyLanguage.optionObj.map(item => item.value)"
                :title="$t('replyLanguageLabel')"
                :fronticon="false"
                :placeholder="
                  settingPreset.replyLanguage.optionObj.find(option => option.value === settingForm.replyLanguage)
                    ?.label || settingForm.replyLanguage
                "
              >
                <template #item="{ item }">
                  {{ settingPreset.replyLanguage.optionObj.find(option => option.value === item)?.label || item }}
                </template>
              </SingleSelect>
            </SettingCard>
            <SettingCard>
              <CustomInput
                v-model.number="settingForm.agentMaxIterations"
                :title="$t('agentMaxIterationsLabel')"
                placeholder="25"
                type="number"
                :min="1"
                :max="500"
                :step="1"
              />
            </SettingCard>
            <SettingCard>
              <CustomInput
                v-model.number="settingForm.llmTimeout"
                :title="$t('llmTimeoutLabel')"
                placeholder="60"
                type="number"
                :min="5"
                :max="300"
                :step="5"
              />
            </SettingCard>
            <SettingCard>
              <CustomInput
                v-model="settingForm.historyDbPath"
                :title="$t('historyDbPathLabel')"
                :placeholder="$t('historyDbPathPlaceholder')"
              >
                <template #input-extra>
                  <CustomButton
                    :icon="FolderOpen"
                    text=""
                    class="bg-surface p-2!"
                    type="secondary"
                    @click="browseDbFile"
                  />
                </template>
              </CustomInput>
              <!-- Server-side file browser -->
              <div v-show="fileBrowser.isOpen" class="mt-2 rounded-md border border-border bg-bg-tertiary p-2 text-sm">
                <div class="mb-1.5 flex items-center gap-2">
                  <button
                    v-if="fileBrowser.parentPath"
                    class="shrink-0 text-accent hover:underline"
                    @click="navigateDir(fileBrowser.parentPath!)"
                  >
                    &uarr; Up
                  </button>
                  <span class="flex-1 truncate text-xs text-tertiary">{{ fileBrowser.currentPath }}</span>
                  <button class="shrink-0 text-secondary hover:text-main" @click="fileBrowser.isOpen = false">
                    &times;
                  </button>
                </div>
                <div class="max-h-48 overflow-y-auto">
                  <div
                    v-for="entry in fileBrowser.entries"
                    :key="entry.path"
                    class="flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 hover:bg-bg-secondary"
                    @click="entry.is_dir ? navigateDir(entry.path) : selectDbFile(entry.path)"
                  >
                    <span class="shrink-0 text-xs">{{ entry.is_dir ? '\uD83D\uDCC1' : '\uD83D\uDCC4' }}</span>
                    <span class="truncate">{{ entry.name }}</span>
                  </div>
                  <div v-if="fileBrowser.entries.length === 0" class="px-1.5 py-1 text-tertiary">
                    No .db files or subdirectories
                  </div>
                </div>
              </div>
            </SettingCard>
            <SettingCard>
              <CustomInput
                v-model.number="settingForm.attachmentCharLimit"
                :title="$t('attachmentCharLimitLabel')"
                :placeholder="$t('attachmentCharLimitPlaceholder')"
                type="number"
                :min="500"
                :step="1000"
              />
            </SettingCard>
            <SettingCard>
              <CustomInput
                v-model="settingForm.tavilyApiKey"
                :title="$t('tavilyApiKeyLabel')"
                :placeholder="$t('tavilyApiKeyPlaceholder')"
              />
            </SettingCard>
            <SettingCard>
              <div class="flex items-center justify-between gap-3 p-2">
                <div class="flex flex-col gap-1">
                  <label for="check-enableMarkdown" class="cursor-pointer text-xs font-semibold text-secondary">
                    {{ t('enableMarkdownLabel') }}
                  </label>
                  <span class="text-xs text-secondary/70">
                    {{ t('enableMarkdownPlaceholder') }}
                  </span>
                </div>
                <input
                  id="check-enableMarkdown"
                  v-model="settingForm.enableMarkdown"
                  type="checkbox"
                  class="h-4 w-4 cursor-pointer"
                />
              </div>
            </SettingCard>
            <SettingCard>
              <div class="flex items-center justify-between gap-3 p-2">
                <div class="flex flex-col gap-1">
                  <label for="check-horizontalToolCalls" class="cursor-pointer text-xs font-semibold text-secondary">
                    {{ t('horizontalToolCallsLabel') }}
                  </label>
                  <span class="text-xs text-secondary/70">
                    {{ t('horizontalToolCallsPlaceholder') }}
                  </span>
                </div>
                <input
                  id="check-horizontalToolCalls"
                  v-model="settingForm.horizontalToolCalls"
                  type="checkbox"
                  class="h-4 w-4 cursor-pointer"
                />
              </div>
            </SettingCard>
          </div>

          <!-- API Provider Settings -->
          <div
            v-show="currentTab === 'provider'"
            class="flex h-full w-full flex-col items-center gap-2 bg-bg-secondary p-1"
          >
            <SettingCard>
              <SingleSelect
                v-model="settingsProvider"
                :tight="false"
                :key-list="settingPreset.api.optionObj.map(item => item.value)"
                :title="$t('providerLabel')"
                :fronticon="false"
                :placeholder="
                  settingPreset.api.optionObj
                    .find(option => option.value === settingsProvider)
                    ?.label || settingsProvider
                "
              >
                <template #item="{ item }">
                  {{
                    settingPreset.api.optionObj
                      .find(option => option.value === item)
                      ?.label || item
                  }}
                </template>
              </SingleSelect>
            </SettingCard>

            <!-- Dynamic API Configuration -->
            <SettingSection
              v-for="platform in Object.values(availableAPIs)"
              v-show="settingsProvider === platform"
              :key="platform"
            >
              <SettingCard v-for="item in getApiInputSettings(platform)" :key="item">
                <CustomInput
                  v-model="settingForm[item as SettingNames]"
                  :title="t(getLabel(item))"
                  :placeholder="t(getPlaceholder(item))"
                />
              </SettingCard>

              <SettingCard v-if="hasCustomModelsSupport(platform)" p1>
                <div class="flex flex-col items-start gap-2 p-3">
                  <CustomInput
                    v-model="newCustomModel[platform]"
                    :title="t('customModelsLabel')"
                    :placeholder="t('customModelPlaceholder')"
                    @keyup.enter="addCustomModel(platform)"
                  >
                    <template #input-extra>
                      <CustomButton
                        :icon="Plus"
                        text=""
                        class="bg-surface p-2!"
                        type="secondary"
                        @click="addCustomModel(platform)"
                      />
                    </template>
                  </CustomInput>
                  <div
                    v-if="customModelsMap[platform] && customModelsMap[platform].length > 0"
                    class="flex flex-wrap gap-1.5"
                  >
                    <span
                      v-for="model in customModelsMap[platform]"
                      :key="model"
                      class="inline-flex items-center gap-1 rounded-sm border border-border p-1 text-xs text-secondary hover:bg-accent/20"
                    >
                      {{ model }}
                      <button
                        class="inline-flex items-center justify-center rounded-sm p-1 text-danger hover:bg-danger/10"
                        @click="removeCustomModel(platform, model)"
                      >
                        <component :is="X" :size="12" />
                      </button>
                    </span>
                  </div>
                </div>
              </SettingCard>
              <SettingCard v-for="item in getApiSelectSettings(platform)" :key="item">
                <SingleSelect
                  v-model="settingForm[item as SettingNames]"
                  :key-list="getMergedModelOptions(platform)"
                  :title="t(getLabel(item))"
                  :fronticon="false"
                  :placeholder="settingForm[item as SettingNames]"
                />
              </SettingCard>
              <SettingCard v-for="item in getApiNumSettings(platform)" :key="item">
                <CustomInput
                  v-model.number="settingForm[item as SettingNames]"
                  :title="t(getLabel(item))"
                  :placeholder="t(getPlaceholder(item))"
                  type="number"
                  :min="getNumericConstraints(item).min"
                  :max="getNumericConstraints(item).max"
                  :step="getNumericConstraints(item).step"
                />
              </SettingCard>
              <SettingCard v-for="item in getApiCheckboxSettings(platform)" :key="item">
                <div class="flex items-center justify-between gap-3 p-2">
                  <div class="flex flex-col gap-1">
                    <label :for="'check-' + item" class="cursor-pointer text-xs font-semibold text-secondary">
                      {{ t(getLabel(item)) }}
                    </label>
                    <span class="text-xs text-secondary/70">
                      {{ t(getPlaceholder(item)) }}
                    </span>
                  </div>
                  <input
                    :id="'check-' + item"
                    v-model="settingForm[item as SettingNames]"
                    type="checkbox"
                    class="h-4 w-4 cursor-pointer"
                  />
                </div>
              </SettingCard>
            </SettingSection>
          </div>

          <!-- MultiAgent Settings -->
          <div
            v-show="currentTab === 'multiagent'"
            class="flex w-full flex-1 flex-col items-center gap-2 bg-bg-secondary p-1"
          >
            <div
              class="flex h-full w-full flex-col gap-2 overflow-auto rounded-md border border-border-secondary p-2 shadow-sm"
            >
              <MultiAgentSettings v-model="multiAgentConfig" />
            </div>
          </div>

          <!-- Quick Actions Settings -->
          <div
            v-show="currentTab === 'quickActions'"
            class="flex w-full flex-1 flex-col items-center gap-2 bg-bg-secondary p-1"
          >
            <div
              class="flex h-full w-full flex-col gap-2 overflow-auto rounded-md border border-border-secondary p-2 shadow-sm"
            >
              <div class="rounded-md border border-border-secondary p-1 shadow-sm">
                <h3 class="text-center text-sm font-semibold text-accent/70">
                  {{ t('quickActions') }}
                </h3>
              </div>
              <div class="rounded-md border border-border-secondary p-1 shadow-sm">
                <p class="text-xs leading-normal font-medium wrap-break-word text-secondary">
                  {{ t('quickActionsDescription') }}
                </p>
              </div>

              <div
                v-for="(slot, idx) in quickActionSlots"
                :key="slot.id"
                class="flex flex-col gap-2 rounded-md border border-border bg-surface p-2 hover:border-accent"
              >
                <div class="flex items-center justify-between gap-2">
                  <div class="flex items-center gap-2">
                    <input
                      type="checkbox"
                      :checked="slot.enabled"
                      class="h-4 w-4 cursor-pointer"
                      @change="toggleSlotEnabled(slot)"
                    />
                    <component
                      :is="ICON_OPTIONS[slot.icon] || ICON_OPTIONS['Sparkle']"
                      :size="16"
                      class="text-accent"
                    />
                    <span class="text-xs font-semibold text-secondary">
                      {{ slot.name || t('quickActionSlot', { n: idx + 1 }) }}
                    </span>
                  </div>
                  <div class="flex shrink-0 gap-1">
                    <CustomButton
                      :icon="editingSlotId === slot.id ? Save : Edit2"
                      text=""
                      :title="editingSlotId === slot.id ? t('save') : t('edit')"
                      class="border-none bg-surface! p-1.5!"
                      type="secondary"
                      :icon-size="14"
                      @click="toggleEditSlot(slot)"
                    />
                    <CustomButton
                      v-if="isSlotModified(slot)"
                      :icon="RotateCcwIcon"
                      text=""
                      :title="t('reset')"
                      class="border-none bg-surface! p-1.5!"
                      type="secondary"
                      :icon-size="14"
                      @click="resetSlot(slot)"
                    />
                  </div>
                </div>

                <div v-if="editingSlotId === slot.id" class="flex flex-col gap-2 border-t border-t-border pt-2">
                  <label class="text-xs font-semibold text-secondary">{{ t('quickActionName') }}</label>
                  <input
                    v-model="slot.name"
                    class="w-full rounded-md border border-border bg-bg-secondary px-2 py-1 text-xs text-main focus:border-accent focus:outline-none"
                    @input="onSlotFieldChange"
                  />

                  <label class="text-xs font-semibold text-secondary">Icon</label>
                  <div class="flex flex-wrap gap-1.5">
                    <button
                      v-for="(iconComp, iconKey) in ICON_OPTIONS"
                      :key="iconKey"
                      class="rounded-md border p-1.5 transition-all duration-fast"
                      :class="
                        slot.icon === iconKey ? 'border-accent bg-accent/20' : 'border-border hover:border-accent-hover'
                      "
                      @click="setSlotIcon(slot, iconKey)"
                    >
                      <component :is="iconComp" :size="16" class="text-secondary" />
                    </button>
                  </div>

                  <label class="text-xs font-semibold text-secondary">{{ $t('userPrompt') }}</label>
                  <textarea
                    v-model="slot.userPrompt"
                    class="min-h-16 w-full rounded-md border border-border bg-bg-secondary p-2 text-xs text-main focus:border-accent focus:outline-none"
                    rows="3"
                    :placeholder="$t('userPromptPlaceholder')"
                    @input="onSlotFieldChange"
                  />
                </div>

              </div>
            </div>
          </div>

          <!-- Tools Settings -->
          <div
            v-show="currentTab === 'tools'"
            class="w-full flex-1 items-center gap-2 overflow-hidden bg-bg-secondary p-1"
          >
            <!-- Word Tools Section -->
            <div
              class="flex h-full w-full flex-col gap-2 overflow-auto rounded-md border border-border-secondary p-2 shadow-sm"
            >
              <div class="rounded-md border border-border-secondary p-1 shadow-sm">
                <h3 class="text-center text-sm font-semibold text-accent/70">
                  {{ t('wordTools') }}
                </h3>
              </div>
              <div class="rounded-md border border-border-secondary p-1 shadow-sm">
                <p class="bord text-xs leading-normal font-medium wrap-break-word text-secondary">
                  {{ t('wordToolsDescription') }}
                </p>
              </div>
              <div class="flex flex-col gap-2">
                <div
                  v-for="tool in wordToolsList"
                  :key="tool.name"
                  class="flex items-center gap-2 rounded-md border border-border bg-surface p-2 hover:border-accent"
                >
                  <input
                    :id="'tool-' + tool.name"
                    type="checkbox"
                    :checked="isToolEnabled(tool.name, !isGeneralTool(tool.name))"
                    class="h-4 w-4 cursor-pointer"
                    @change="toggleTool(tool.name, !isGeneralTool(tool.name))"
                  />
                  <div class="flex flex-col" @click="toggleTool(tool.name, !isGeneralTool(tool.name))">
                    <label :for="'tool-' + tool.name" class="text-xs font-semibold text-secondary">{{
                      $t(`wordTool_${tool.name}`)
                    }}</label>
                    <span class="text-xs text-secondary/90">
                      {{ $t(`wordTool_${tool.name}_desc`) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- MCP Servers Settings -->
          <div
            v-show="currentTab === 'mcp'"
            class="w-full flex-1 items-center gap-2 overflow-hidden bg-bg-secondary p-1"
          >
            <div
              class="flex h-full w-full flex-col gap-2 overflow-auto rounded-md border border-border-secondary p-2 shadow-sm"
            >
              <div class="rounded-md border border-border-secondary p-1 shadow-sm">
                <h3 class="text-center text-sm font-semibold text-accent/70">
                  {{ t('mcpServers') }}
                </h3>
              </div>
              <div class="rounded-md border border-border-secondary p-1 shadow-sm">
                <p class="text-xs leading-normal font-medium wrap-break-word text-secondary">
                  {{ t('mcpServersDescription') }}
                </p>
              </div>

              <!-- Error display -->
              <div
                v-if="mcpError"
                class="rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-700 dark:border-red-700 dark:bg-red-900/20 dark:text-red-400"
              >
                {{ mcpError }}
                <button class="ml-2 underline" @click="mcpError = ''">dismiss</button>
              </div>

              <!-- Add Server Form -->
              <div class="flex flex-col gap-1.5 rounded-md border border-border bg-surface p-2">
                <span class="text-xs font-semibold text-secondary">{{ t('mcpAddServer') }}</span>
                <input
                  v-model="mcpNewName"
                  :placeholder="t('mcpServerName')"
                  class="rounded-md border border-border bg-bg-secondary px-2 py-1 text-xs text-main focus:border-accent focus:outline-none"
                />
                <input
                  v-model="mcpNewCommand"
                  :placeholder="t('mcpServerCommand')"
                  class="rounded-md border border-border bg-bg-secondary px-2 py-1 text-xs font-mono text-main focus:border-accent focus:outline-none"
                />
                <input
                  v-model="mcpNewArgs"
                  :placeholder="t('mcpServerArgs')"
                  class="rounded-md border border-border bg-bg-secondary px-2 py-1 text-xs font-mono text-main focus:border-accent focus:outline-none"
                />
                <input
                  v-model="mcpNewEnv"
                  :placeholder="t('mcpServerEnv')"
                  class="rounded-md border border-border bg-bg-secondary px-2 py-1 text-xs font-mono text-main focus:border-accent focus:outline-none"
                />
                <CustomButton
                  :icon="Plus"
                  :text="t('mcpAddServer')"
                  type="primary"
                  class="self-end p-1! text-xs"
                  @click="handleAddMcpServer"
                />
              </div>

              <!-- Server List -->
              <div v-for="server in mcpServers" :key="server.id" class="flex flex-col gap-1.5 rounded-md border border-border bg-surface p-2">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <span
                      class="inline-block h-2 w-2 rounded-full"
                      :class="server.status === 'connected' ? 'bg-green-500' : 'bg-gray-400'"
                    />
                    <span class="text-xs font-semibold text-main">{{ server.name }}</span>
                    <span class="text-xs text-secondary/70 font-mono">{{ server.command }} {{ server.args.join(' ') }}</span>
                  </div>
                  <div class="flex gap-1">
                    <CustomButton
                      v-if="server.status === 'disconnected'"
                      :text="t('mcpConnect')"
                      type="primary"
                      class="p-1! text-xs"
                      :disabled="mcpLoading[server.id]"
                      @click="handleConnectMcp(server.id)"
                    />
                    <CustomButton
                      v-else
                      :text="t('mcpDisconnect')"
                      type="secondary"
                      class="p-1! text-xs"
                      :disabled="mcpLoading[server.id]"
                      @click="handleDisconnectMcp(server.id)"
                    />
                    <CustomButton
                      :icon="Trash2"
                      text=""
                      type="secondary"
                      class="border-none! p-1!"
                      :icon-size="14"
                      @click="handleDeleteMcpServer(server.id)"
                    />
                  </div>
                </div>

                <!-- Tools list (when connected) -->
                <div v-if="server.status === 'connected' && server.tools.length > 0" class="flex flex-col gap-1 pl-4">
                  <span class="text-xs text-secondary">{{ server.tools.length }} {{ t('mcpToolsDiscovered') }}</span>
                  <div
                    v-for="tool in server.tools"
                    :key="tool.name"
                    class="flex items-center gap-2 rounded-md border border-border bg-bg-secondary p-1.5 hover:border-accent"
                  >
                    <input
                      :id="'mcp-tool-' + tool.name"
                      type="checkbox"
                      :checked="enabledMcpTools.has(tool.name)"
                      class="h-3.5 w-3.5 cursor-pointer"
                      @change="toggleMcpTool(tool.name)"
                    />
                    <div class="flex flex-col cursor-pointer" @click="toggleMcpTool(tool.name)">
                      <label :for="'mcp-tool-' + tool.name" class="text-xs font-semibold text-secondary">{{ tool.original_name }}</label>
                      <span v-if="tool.description" class="text-xs text-secondary/80">{{ tool.description }}</span>
                    </div>
                  </div>
                </div>
                <div v-else-if="server.status === 'connected'" class="pl-4 text-xs text-secondary/70 italic">
                  {{ t('mcpNoTools') }}
                </div>
              </div>
            </div>
          </div>

          <!-- System Prompts Settings -->
          <div
            v-show="currentTab === 'systemPrompts'"
            class="flex w-full flex-1 flex-col items-center gap-2 bg-bg-secondary p-1"
          >
            <div
              class="flex h-full w-full flex-col gap-2 overflow-auto rounded-md border border-border-secondary p-2 shadow-sm"
            >
              <div class="flex items-center justify-between">
                <h3 class="text-center text-sm font-semibold text-main">
                  {{ t('systemPrompts') }}
                </h3>
                <CustomButton
                  :icon="Plus"
                  text=""
                  :title="t('addSystemPrompt')"
                  class="p-1!"
                  type="secondary"
                  @click="addNewPreset"
                />
              </div>
              <div class="rounded-md border border-border-secondary p-1 shadow-sm">
                <p class="text-xs leading-normal font-medium wrap-break-word text-secondary">
                  {{ t('systemPromptsDescription') }}
                </p>
              </div>

              <div
                v-for="preset in systemPromptPresets"
                :key="preset.id"
                class="rounded-md border border-border bg-surface p-3"
              >
                <div class="flex items-start justify-between">
                  <div class="flex flex-1 flex-wrap items-center gap-2">
                    <input
                      v-if="editingPresetId === preset.id"
                      v-model="editingPreset.name"
                      class="max-w-37.5 min-w-25 flex-1 rounded-md border border-border px-2 py-1 text-sm font-semibold text-secondary focus:border-accent focus:outline-none"
                      @keyup.enter="savePresetEdit"
                    />
                    <span v-else class="text-sm font-semibold text-main">{{ preset.name }}</span>
                  </div>
                  <div class="flex shrink-0 gap-1">
                    <CustomButton
                      type="secondary"
                      :title="t('edit')"
                      :icon="Edit2"
                      class="border-none! bg-surface! p-1.5!"
                      :icon-size="14"
                      text=""
                      @click="startEditPreset(preset)"
                    />
                    <CustomButton
                      class="border-none! bg-surface! p-1.5!"
                      :title="t('delete')"
                      type="secondary"
                      :icon="Trash2"
                      text=""
                      :icon-size="14"
                      @click="deletePreset(preset.id)"
                    />
                  </div>
                </div>

                <div v-if="editingPresetId === preset.id" class="mt-3 border-t border-t-border pt-3">
                  <label class="mb-1 block text-xs font-semibold text-secondary">{{ $t('systemPrompt') }}</label>
                  <textarea
                    v-model="editingPreset.systemPrompt"
                    class="w-full rounded-sm border border-border bg-bg-secondary px-2 py-1 text-sm leading-normal text-main transition-all duration-200 ease-apple focus:border-accent focus:outline-none"
                    rows="4"
                    :placeholder="$t('systemPromptPlaceholder')"
                  />

                  <div class="mt-3 flex gap-2">
                    <CustomButton type="primary" class="flex-1" :text="t('save')" @click="savePresetEdit" />
                    <CustomButton type="secondary" class="flex-1" :text="t('cancel')" @click="cancelPresetEdit" />
                  </div>
                </div>

                <div v-else class="mt-2">
                  <p class="overflow-hidden text-xs font-semibold text-ellipsis text-secondary">
                    {{ preset.systemPrompt.substring(0, 100) }}{{ preset.systemPrompt.length > 100 ? '...' : '' }}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
import {
  ArrowLeft,
  Cpu,
  Edit2,
  FolderOpen,
  Globe,
  MessageSquare,
  Plug2,
  Plus,
  RotateCcwIcon,
  Save,
  Trash2,
  Users,
  Wrench,
  X,
  Zap,
} from 'lucide-vue-next'
import { onBeforeMount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import {
  addMcpServer,
  browseDirContents,
  connectMcpServer,
  deleteMcpServer,
  disconnectMcpServer,
  fetchMcpServers,
  getHistoryPath,
  type McpServerInfo,
  type McpToolInfo,
  setHistoryPath,
} from '@/api/backend'
import type { MultiAgentConfig } from '@/api/types'
import CustomButton from '@/components/CustomButton.vue'
import CustomInput from '@/components/CustomInput.vue'
import MultiAgentSettings from '@/components/MultiAgentSettings.vue'
import SettingCard from '@/components/SettingCard.vue'
import SettingSection from '@/components/SettingSection.vue'
import SingleSelect from '@/components/SingleSelect.vue'
import { getLabel, getPlaceholder, optionLists } from '@/utils/common'
import {
  availableAPIs,
  DEFAULT_QUICK_ACTION_SLOTS,
  getQuickActionSlots,
  getSystemPromptPresets,
  ICON_OPTIONS,
  type QuickActionSlot,
  type SystemPromptPreset,
} from '@/utils/constant'
import { localStorageKey } from '@/utils/enum'
import { getGeneralToolDefinitions } from '@/utils/generalTools'
import useSettingForm from '@/utils/settingForm'
import { Setting_Names, SettingNames, settingPreset } from '@/utils/settingPreset'
import { getWordToolDefinitions } from '@/utils/wordTools'
const { t } = useI18n()
const router = useRouter()
const settingForm = useSettingForm()

const currentTab = ref('provider')

// Local-only ref for navigating provider config panels in Settings.
// This must NOT be tied to settingForm.api, which controls the active
// provider on the main page. Changing this only selects which panel to show.
const settingsProvider = ref(localStorage.getItem(localStorageKey.api) || 'official')

// Word tools list
const wordToolsList = [...getGeneralToolDefinitions(), ...getWordToolDefinitions()]

const newCustomModel = ref<Record<string, string>>({})
const customModelsMap = ref<Record<string, string[]>>({})

// Quick action slots management
const quickActionSlots = ref<QuickActionSlot[]>(getQuickActionSlots())
const editingSlotId = ref<string>('')

// System prompt presets management
const systemPromptPresets = ref<SystemPromptPreset[]>(getSystemPromptPresets())
const editingPresetId = ref<string>('')
const editingPreset = ref<SystemPromptPreset>({ id: '', name: '', systemPrompt: '' })

// MultiAgent configuration state
const multiAgentConfig = ref<MultiAgentConfig>({
  mode: 'parallel',
  operatingMode: 'legacy',
  maxRounds: 3,
  experts: [
    {
      id: 'expert_1',
      name: 'Expert_1',
      provider: 'official',
      model: '',
      temperature: 1.0,
    },
    {
      id: 'expert_2',
      name: 'Expert_2',
      provider: 'anthropic',
      model: '',
      temperature: 1.0,
    },
    {
      id: 'expert_3',
      name: 'Expert_3',
      provider: 'official',
      model: '',
      temperature: 1.0,
    },
    {
      id: 'expert_4',
      name: 'Expert_4',
      provider: 'official',
      model: '',
      temperature: 1.0,
    },
  ],
  overseer: {
    id: 'overseer',
    name: 'Overseer',
    provider: 'anthropic',
    model: '',
    temperature: 1.0,
  },
})

// Tool enable/disable state
const enabledWordTools = ref<Set<string>>(new Set())
const enabledGeneralTools = ref<Set<string>>(new Set())

// MCP state
const mcpServers = ref<McpServerInfo[]>([])
const enabledMcpTools = ref<Set<string>>(new Set())
const mcpNewName = ref('')
const mcpNewCommand = ref('')
const mcpNewArgs = ref('')
const mcpNewEnv = ref('')
const mcpLoading = ref<Record<string, boolean>>({})
const mcpError = ref<string>('')

const tabs = [
  { id: 'general', label: 'general', defaultLabel: 'General', icon: Globe },
  {
    id: 'provider',
    label: 'apiProvider',
    defaultLabel: 'API Provider',
    icon: Cpu,
  },
  {
    id: 'multiagent',
    label: 'multiAgent',
    defaultLabel: 'Multi-Agent',
    icon: Users,
  },
  {
    id: 'quickActions',
    label: 'quickActions',
    defaultLabel: 'Quick Actions',
    icon: Zap,
  },
  {
    id: 'systemPrompts',
    label: 'systemPrompts',
    defaultLabel: 'System Prompts',
    icon: MessageSquare,
  },
  {
    id: 'tools',
    label: 'tools',
    defaultLabel: 'Tools',
    icon: Wrench,
  },
  {
    id: 'mcp',
    label: 'mcpServers',
    defaultLabel: 'MCP',
    icon: Plug2,
  },
]

const getApiInputSettings = (platform: string) => {
  return Object.keys(settingForm.value).filter(
    key =>
      key.startsWith(platform) && settingPreset[key as SettingNames].type === 'input' && !key.endsWith('CustomModel'),
  )
}

const getNumericConstraints = (item: string): { min: number; max?: number; step: number } => {
  if (item.includes('Temperature')) return { min: 0, max: 2, step: 0.1 }
  if (item.includes('MaxContextTokens')) return { min: 4000, step: 1000 }
  if (item.includes('attachmentCharLimit')) return { min: 500, step: 1000 }
  return { min: 0, step: 1 }
}

const getApiNumSettings = (platform: string) => {
  return Object.keys(settingForm.value).filter(
    key => key.startsWith(platform) && settingPreset[key as SettingNames].type === 'inputNum',
  )
}

const getApiCheckboxSettings = (platform: string) => {
  return Object.keys(settingForm.value).filter(
    key => key.startsWith(platform) && settingPreset[key as SettingNames].type === 'checkbox',
  )
}

const getApiSelectSettings = (platform: string) => {
  return Object.keys(settingForm.value).filter(
    key => key.startsWith(platform) && settingPreset[key as SettingNames].type === 'select',
  )
}

const getCustomModelsKey = (platform: string): SettingNames | null => {
  const key = `${platform}CustomModels` as SettingNames
  return settingPreset[key] ? key : null
}

const loadCustomModels = () => {
  const platforms = ['official', 'anthropic', 'gemini', 'ollama', 'groq', 'azure', 'lmstudio']
  platforms.forEach(platform => {
    const key = getCustomModelsKey(platform)
    if (key && settingPreset[key].getFunc) {
      customModelsMap.value[platform] = settingPreset[key].getFunc() as string[]
    }
  })
}

const addCustomModel = (platform: string) => {
  const model = newCustomModel.value[platform]?.trim()
  if (!model) return

  const key = getCustomModelsKey(platform)
  if (!key) return

  if (!customModelsMap.value[platform]) {
    customModelsMap.value[platform] = []
  }

  if (!customModelsMap.value[platform].includes(model)) {
    customModelsMap.value[platform].push(model)
    ;(settingPreset[key] as any).saveFunc(customModelsMap.value[platform])
    newCustomModel.value[platform] = ''
  }
}

const removeCustomModel = (platform: string, model: string) => {
  const key = getCustomModelsKey(platform)
  if (!key) return

  customModelsMap.value[platform] = customModelsMap.value[platform].filter(m => m !== model)
  ;(settingPreset[key] as any).saveFunc(customModelsMap.value[platform])

  // If the removed model was selected, switch to first available
  const selectKey = `${platform}ModelSelect` as SettingNames
  if (settingForm.value[selectKey] === model) {
    const options = getMergedModelOptions(platform)
    if (options.length > 0) {
      ;(settingForm.value as any)[selectKey] = options[0]
    }
  }
}

const getMergedModelOptions = (platform: string) => {
  const selectKey = `${platform}ModelSelect` as SettingNames
  const presetOptions = settingPreset[selectKey]?.optionList || []
  const customModels = customModelsMap.value[platform] || []

  return [...customModels, ...presetOptions]
}

const hasCustomModelsSupport = (platform: string) => {
  return getCustomModelsKey(platform) !== null
}

const addWatch = () => {
  Setting_Names.forEach(key => {
    watch(
      () => settingForm.value[key],
      () => {
        if (settingPreset[key].saveFunc) {
          ;(settingPreset[key] as any).saveFunc(settingForm.value[key])
          console.log(`Saved setting ${key} via custom saveFunc with value: ${settingForm.value[key]}`)
          return
        }
        localStorage.setItem(settingPreset[key].saveKey || key, settingForm.value[key] as string)
        console.log(`Saved setting ${key} to localStorage with value: ${settingForm.value[key]}`)
      },
      { deep: true },
    )
  })
}

// --- Quick Action Slots ---

const saveQuickActionSlots = () => {
  localStorage.setItem('quickActionSlots', JSON.stringify(quickActionSlots.value))
}

const toggleSlotEnabled = (slot: QuickActionSlot) => {
  slot.enabled = !slot.enabled
  saveQuickActionSlots()
}

const toggleEditSlot = (slot: QuickActionSlot) => {
  editingSlotId.value = editingSlotId.value === slot.id ? '' : slot.id
}

const onSlotFieldChange = () => {
  saveQuickActionSlots()
}

const setSlotIcon = (slot: QuickActionSlot, iconKey: string) => {
  slot.icon = iconKey
  saveQuickActionSlots()
}

const isSlotModified = (slot: QuickActionSlot): boolean => {
  const def = DEFAULT_QUICK_ACTION_SLOTS.find(d => d.id === slot.id)
  if (!def) return slot.name.trim() !== '' || slot.userPrompt.trim() !== ''
  return (
    slot.name !== def.name ||
    slot.icon !== def.icon ||
    slot.userPrompt !== def.userPrompt ||
    slot.enabled !== def.enabled
  )
}

const resetSlot = (slot: QuickActionSlot) => {
  const def = DEFAULT_QUICK_ACTION_SLOTS.find(d => d.id === slot.id)
  if (def) {
    Object.assign(slot, { ...def })
  } else {
    slot.name = ''
    slot.userPrompt = ''
    slot.icon = 'Sparkle'
    slot.enabled = false
  }
  saveQuickActionSlots()
  editingSlotId.value = ''
}

// --- System Prompt Presets ---

const saveSystemPromptPresets = () => {
  localStorage.setItem('systemPromptPresets', JSON.stringify(systemPromptPresets.value))
}

const addNewPreset = () => {
  const preset: SystemPromptPreset = {
    id: `sp_${Date.now()}`,
    name: `Preset ${systemPromptPresets.value.length + 1}`,
    systemPrompt: '',
  }
  systemPromptPresets.value.push(preset)
  saveSystemPromptPresets()
  startEditPreset(preset)
}

const startEditPreset = (preset: SystemPromptPreset) => {
  editingPresetId.value = preset.id
  editingPreset.value = { ...preset }
}

const savePresetEdit = () => {
  const index = systemPromptPresets.value.findIndex(p => p.id === editingPresetId.value)
  if (index !== -1) {
    systemPromptPresets.value[index] = { ...editingPreset.value }
    saveSystemPromptPresets()
  }
  editingPresetId.value = ''
}

const cancelPresetEdit = () => {
  editingPresetId.value = ''
}

const deletePreset = (id: string) => {
  const index = systemPromptPresets.value.findIndex(p => p.id === id)
  if (index !== -1) {
    systemPromptPresets.value.splice(index, 1)
    saveSystemPromptPresets()
  }
  // If deleted preset was active, clear the selection
  if (localStorage.getItem('activeSystemPromptId') === id) {
    localStorage.removeItem('activeSystemPromptId')
  }
}

const loadToolPreferences = () => {
  const wordTools = localStorage.getItem('enabledWordTools')
  const generalTools = localStorage.getItem('enabledGeneralTools')

  if (wordTools) {
    try {
      enabledWordTools.value = new Set(JSON.parse(wordTools))
    } catch {
      enabledWordTools.value = new Set(getWordToolDefinitions().map(t => t.name))
    }
  } else {
    enabledWordTools.value = new Set(getWordToolDefinitions().map(t => t.name))
  }

  if (generalTools) {
    try {
      enabledGeneralTools.value = new Set(JSON.parse(generalTools))
    } catch {
      const generalToolNames = getGeneralToolDefinitions().map(t => t.name)
      enabledGeneralTools.value = new Set(generalToolNames)
    }
  } else {
    const generalToolNames = getGeneralToolDefinitions().map(t => t.name)
    enabledGeneralTools.value = new Set(generalToolNames)
  }
}

const saveToolPreferences = () => {
  localStorage.setItem('enabledWordTools', JSON.stringify([...enabledWordTools.value]))
  localStorage.setItem('enabledGeneralTools', JSON.stringify([...enabledGeneralTools.value]))
}

const toggleTool = (toolName: string, isWordTool: boolean) => {
  if (isWordTool) {
    if (enabledWordTools.value.has(toolName)) {
      enabledWordTools.value.delete(toolName)
    } else {
      enabledWordTools.value.add(toolName)
    }
  } else {
    if (enabledGeneralTools.value.has(toolName)) {
      enabledGeneralTools.value.delete(toolName)
    } else {
      enabledGeneralTools.value.add(toolName)
    }
  }
  saveToolPreferences()
}

const isToolEnabled = (toolName: string, isWordTool: boolean): boolean => {
  return isWordTool ? enabledWordTools.value.has(toolName) : enabledGeneralTools.value.has(toolName)
}

const isGeneralTool = (toolName: string): boolean => {
  const generalToolNames = getGeneralToolDefinitions().map(t => t.name)
  return generalToolNames.includes(toolName as any)
}

// --- MCP Server Management ---

const loadMcpToolPreferences = () => {
  const stored = localStorage.getItem('enabledMcpTools')
  if (stored) {
    try {
      enabledMcpTools.value = new Set(JSON.parse(stored))
    } catch {
      enabledMcpTools.value = new Set()
    }
  }
}

const saveMcpToolPreferences = () => {
  localStorage.setItem('enabledMcpTools', JSON.stringify([...enabledMcpTools.value]))
}

const toggleMcpTool = (toolName: string) => {
  if (enabledMcpTools.value.has(toolName)) {
    enabledMcpTools.value.delete(toolName)
  } else {
    enabledMcpTools.value.add(toolName)
  }
  saveMcpToolPreferences()
}

const loadMcpServers = async () => {
  try {
    mcpServers.value = await fetchMcpServers()
  } catch (e: any) {
    mcpError.value = e.message
  }
}

const handleAddMcpServer = async () => {
  if (!mcpNewName.value.trim() || !mcpNewCommand.value.trim()) return
  mcpError.value = ''

  // Parse env vars from "KEY=VALUE" lines
  const env: Record<string, string> = {}
  for (const line of mcpNewEnv.value.split('\n').concat(mcpNewEnv.value.split(','))) {
    const trimmed = line.trim()
    if (!trimmed || !trimmed.includes('=')) continue
    const eqIdx = trimmed.indexOf('=')
    env[trimmed.slice(0, eqIdx).trim()] = trimmed.slice(eqIdx + 1).trim()
  }

  try {
    await addMcpServer({
      name: mcpNewName.value.trim(),
      command: mcpNewCommand.value.trim(),
      args: mcpNewArgs.value.trim() ? mcpNewArgs.value.trim().split(/\s+/) : [],
      env,
    })
    mcpNewName.value = ''
    mcpNewCommand.value = ''
    mcpNewArgs.value = ''
    mcpNewEnv.value = ''
    await loadMcpServers()
  } catch (e: any) {
    mcpError.value = e.message
  }
}

const handleDeleteMcpServer = async (serverId: string) => {
  mcpError.value = ''
  try {
    // Remove any enabled tools from this server
    const server = mcpServers.value.find(s => s.id === serverId)
    if (server) {
      for (const tool of server.tools) {
        enabledMcpTools.value.delete(tool.name)
      }
      saveMcpToolPreferences()
    }
    await deleteMcpServer(serverId)
    await loadMcpServers()
  } catch (e: any) {
    mcpError.value = e.message
  }
}

const handleConnectMcp = async (serverId: string) => {
  mcpError.value = ''
  mcpLoading.value[serverId] = true
  try {
    const tools = await connectMcpServer(serverId)
    // Auto-enable all newly discovered tools
    for (const tool of tools) {
      enabledMcpTools.value.add(tool.name)
    }
    saveMcpToolPreferences()
    await loadMcpServers()
  } catch (e: any) {
    mcpError.value = e.message
  } finally {
    mcpLoading.value[serverId] = false
  }
}

const handleDisconnectMcp = async (serverId: string) => {
  mcpError.value = ''
  mcpLoading.value[serverId] = true
  try {
    // Remove enabled tools for this server
    const server = mcpServers.value.find(s => s.id === serverId)
    if (server) {
      for (const tool of server.tools) {
        enabledMcpTools.value.delete(tool.name)
      }
      saveMcpToolPreferences()
    }
    await disconnectMcpServer(serverId)
    await loadMcpServers()
  } catch (e: any) {
    mcpError.value = e.message
  } finally {
    mcpLoading.value[serverId] = false
  }
}

// MultiAgent configuration persistence
const loadMultiAgentConfig = () => {
  const stored = localStorage.getItem('multiAgentConfig')
  if (stored) {
    try {
      const parsed = JSON.parse(stored)
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
      multiAgentConfig.value = parsed
    } catch (error) {
      console.error('Error loading multi-agent config:', error)
    }
  }
}

const saveMultiAgentConfig = () => {
  localStorage.setItem('multiAgentConfig', JSON.stringify(multiAgentConfig.value))
}

// Watch for config changes
watch(
  multiAgentConfig,
  () => {
    saveMultiAgentConfig()
  },
  { deep: true },
)

// Sync history DB path with backend when it changes in settings
let historyDbPathDebounceTimer: ReturnType<typeof setTimeout> | null = null
let historyDbPathSkipNextWatch = false
watch(
  () => settingForm.value.historyDbPath,
  newPath => {
    if (historyDbPathSkipNextWatch) {
      historyDbPathSkipNextWatch = false
      return
    }
    if (historyDbPathDebounceTimer) clearTimeout(historyDbPathDebounceTimer)
    historyDbPathDebounceTimer = setTimeout(() => {
      setHistoryPath(newPath as string).catch(err => {
        console.error('[Settings] Failed to set history path:', err)
      })
    }, 800)
  },
)

// Server-side file browser state
const fileBrowser = ref({
  isOpen: false,
  currentPath: '',
  parentPath: null as string | null,
  entries: [] as { name: string; path: string; is_dir: boolean }[],
})

const navigateDir = async (path: string) => {
  const result = await browseDirContents(path)
  fileBrowser.value = {
    isOpen: true,
    currentPath: result.current_path,
    parentPath: result.parent_path,
    entries: result.entries,
  }
}

const selectDbFile = (path: string) => {
  settingForm.value.historyDbPath = path
  fileBrowser.value.isOpen = false
}

const browseDbFile = async () => {
  try {
    await navigateDir('')
  } catch (err) {
    console.error('[Settings] Failed to open file browser:', err)
    alert(err instanceof Error ? err.message : String(err))
  }
}

onBeforeMount(async () => {
  loadCustomModels()
  loadToolPreferences()
  loadMcpToolPreferences()
  loadMultiAgentConfig()
  loadMcpServers()

  // Fetch the actual DB path from backend before setting up watchers,
  // so the field shows the real path (including the default) instead of being empty.
  try {
    const actualPath = await getHistoryPath()
    if (actualPath) {
      historyDbPathSkipNextWatch = true
      settingForm.value.historyDbPath = actualPath
    }
  } catch (err) {
    console.error('[Settings] Failed to fetch history path from backend:', err)
  }

  addWatch()
})

function backToHome() {
  router.push('/')
}
</script>
