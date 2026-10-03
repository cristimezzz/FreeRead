// SPDX-License-Identifier: AGPL-3.0-only
import { Component } from 'react';
import type { ReactNode } from 'react';
import type { Text } from '../i18n/text';
import { errorKey } from '../ipc/api';

export class ReaderBoundary extends Component<{
  t: Text; onError: (key: string) => void; onClose: () => void; children: ReactNode;
}, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  override componentDidCatch(cause: unknown) { this.props.onError(errorKey(cause)); }
  override render() {
    return this.state.failed ? <main className="fr-loading">
      <button onClick={this.props.onClose}>{this.props.t('reader.back')}</button>
    </main> : this.props.children;
  }
}
