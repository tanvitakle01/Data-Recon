import { useContext } from "react";
import { TicketingContext } from "./ticketingContextObject";

export function useTicketing() {
  const ctx = useContext(TicketingContext);
  if (!ctx) throw new Error("useTicketing must be used within a TicketingProvider");
  return ctx;
}
