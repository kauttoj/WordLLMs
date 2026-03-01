import { BaseMessage } from '@langchain/core/messages'

export class ToolCallMessage extends BaseMessage {
  toolName: string

  constructor(toolName: string) {
    super({
      content: `Tool: ${toolName}`,
      additional_kwargs: { toolName }
    })
    this.toolName = toolName
  }

  _getType(): string {
    return 'tool_call'
  }
}
