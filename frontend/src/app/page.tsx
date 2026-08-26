import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { listConversations } from "@/lib/backend";
import ChatApp from "@/components/ChatApp";

export default async function Home() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  const conversations = await listConversations();

  return <ChatApp initialConversations={conversations} userEmail={session.user.email ?? null} />;
}
