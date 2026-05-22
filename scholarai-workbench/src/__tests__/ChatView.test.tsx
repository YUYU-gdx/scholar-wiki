import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatView from '../components/ChatView';
import { api } from '../api';

class MockEventSource {
  listeners = new Map<string, Array<(event: MessageEvent) => void>>();

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    const current = this.listeners.get(type) || [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  close() {}

  emit(type: string, payload: unknown) {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    for (const listener of this.listeners.get(type) || []) listener(event);
  }
}

vi.mock('../api', () => ({
  api: {
    chat: {
      listSessions: vi.fn(),
      getSession: vi.fn(),
      createSession: vi.fn(),
      deleteSession: vi.fn(),
      sendMessage: vi.fn(),
      streamEvents: vi.fn(),
    },
  },
}));

vi.mock('../app-context', () => ({
  useApp: () => ({
    sessions: [{ session_id: 'session-1', title: 'Knowledge QA', default_mode: 'agent', library_id: 'library-1' }],
    setSessions: vi.fn(),
    activeSessionId: 'session-1',
    setActiveSessionId: vi.fn(),
    activeLibraryId: 'library-1',
    setSelectedPaperId: vi.fn(),
    setSelectedPaperLibraryId: vi.fn(),
    setCurrentView: vi.fn(),
  }),
}));

describe('ChatView', () => {
  let source: MockEventSource;

  beforeEach(() => {
    source = new MockEventSource();
    vi.mocked(api.chat.listSessions).mockResolvedValue({ sessions: [] });
    vi.mocked(api.chat.sendMessage).mockResolvedValue({
      session_id: 'session-1',
      user_message_id: 'user-1',
      assistant_message_id: 'assistant-1',
      stream_url: '/stream',
    });
    vi.mocked(api.chat.streamEvents).mockReturnValue(source as unknown as EventSource);
  });

  it('renders the complete final answer in knowledge QA when tool trace events are present', async () => {
    const fullAnswer = [
      '# Knowledge Answer',
      '',
      'Opening paragraph: this answer starts with the key finding.',
      '',
      '## Evidence',
      '',
      '- First full evidence item.',
      '- Second full evidence item.',
      '',
      '```text',
      'COMPLETE_PROCESS_TRACE_VISIBLE',
      '```',
      '',
      'Closing sentence: the final answer is visible through the end.',
    ].join('\n');

    render(<ChatView />);

    const textbox = screen.getByRole('textbox');
    fireEvent.change(textbox, { target: { value: 'Answer with evidence' } });
    fireEvent.keyDown(textbox, { key: 'Enter' });

    await waitFor(() => expect(api.chat.streamEvents).toHaveBeenCalledWith('session-1', 'assistant-1'));

    act(() => {
      source.emit('tool_call', {
        name: 'rag_search',
        arguments: { query: 'evidence' },
        result: { hits: [{ paper_id: 'paper-1' }] },
      });
      source.emit('completed', {
        answer: fullAnswer,
        tool_trace: [{
          event: 'tool_call',
          name: 'rag_search',
          arguments: { query: 'evidence' },
          result: { hits: [{ paper_id: 'paper-1' }] },
        }],
      });
    });

    const renderedAnswers = screen.getAllByText((_, element) => (
      element?.textContent?.includes('Knowledge Answer')
      && element.textContent.includes('Opening paragraph: this answer starts with the key finding.')
      && element.textContent.includes('Evidence')
      && element.textContent.includes('First full evidence item.')
      && element.textContent.includes('Second full evidence item.')
      && element.textContent.includes('COMPLETE_PROCESS_TRACE_VISIBLE')
      && element.textContent.includes('Closing sentence: the final answer is visible through the end.')
    ));
    expect(renderedAnswers.length).toBeGreaterThan(0);
    expect(screen.getByText(/RAG/)).toBeInTheDocument();
  });
});
