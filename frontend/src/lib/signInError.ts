/** A failed sign-in, carrying the server's machine-readable reason (COMPANY_REQUIRED, ...). */
export class SignInError extends Error {
  code: string;
  status: number;
  constructor(message: string, code = "UNKNOWN", status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}
