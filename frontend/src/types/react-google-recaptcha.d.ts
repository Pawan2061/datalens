declare module "react-google-recaptcha" {
  import * as React from "react";

  export interface ReCAPTCHAProps {
    sitekey: string;
    theme?: "dark" | "light";
    size?: "compact" | "normal" | "invisible";
    onChange?: (token: string | null) => void;
    onExpired?: () => void;
    onErrored?: () => void;
    ref?: React.Ref<ReCAPTCHA>;
  }

  export default class ReCAPTCHA extends React.Component<ReCAPTCHAProps> {
    reset(): void;
    execute(): void;
    getValue(): string | null;
  }
}
