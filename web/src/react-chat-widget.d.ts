declare module "react-chat-widget" {
  import type { FC, ReactNode } from "react";

  export type WidgetProps = {
    title?: string;
    titleAvatar?: string;
    subtitle?: string;
    senderPlaceHolder?: string;
    handleNewUserMessage: (msg: string) => void;
    handleQuickButtonClicked?: (value: string) => void;
    emojis?: boolean;
    showBadge?: boolean;
    showCloseButton?: boolean;
    fullScreenMode?: boolean;
    autofocus?: boolean;
    launcher?: ReactNode;
  };

  export const Widget: FC<WidgetProps>;
  export function addResponseMessage(text: string, id?: string): void;
  export function addUserMessage(text: string, id?: string): void;
  export function toggleWidget(open?: boolean): void;
  export function dropMessages(): void;
}
