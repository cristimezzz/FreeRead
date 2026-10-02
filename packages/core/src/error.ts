import type { IpcPayloads } from './ipc-payloads.generated';

export type AppErrorWire = IpcPayloads['ErrorObject'];
export type AppErrorOptions = Omit<AppErrorWire, 'code' | 'message'> & {
  message?: string;
  cause?: unknown;
};

export class AppError extends Error {
  override readonly name = 'AppError';
  readonly code: AppErrorWire['code'];
  readonly category: AppErrorWire['category'];
  readonly severity: AppErrorWire['severity'];
  readonly retryable: boolean;
  readonly i18nKey: string;
  readonly details: Readonly<NonNullable<AppErrorWire['details']>>;

  constructor(code: AppErrorWire['code'], options: AppErrorOptions) {
    super(options.message ?? code, { cause: options.cause });
    this.code = code;
    this.category = options.category;
    this.severity = options.severity;
    this.retryable = options.retryable;
    this.i18nKey = options.i18nKey;
    this.details = Object.freeze({ ...options.details });
  }

  toWire(): AppErrorWire {
    return { code: this.code, category: this.category, severity: this.severity,
      retryable: this.retryable, i18nKey: this.i18nKey, details: { ...this.details },
      message: this.message };
  }

  static fromWire(wire: AppErrorWire): AppError {
    return new AppError(wire.code, wire);
  }
}

export function toAppError(cause: unknown, fallback: AppErrorWire['code'] = 'FR-SYS-003'): AppError {
  return cause instanceof AppError ? cause : new AppError(fallback, {
    category: 'system', severity: 'fatal', retryable: false,
    i18nKey: `errors.${fallback}`, cause,
  });
}
