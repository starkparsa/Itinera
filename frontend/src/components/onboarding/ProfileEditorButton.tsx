"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import OnboardingFlow from "./OnboardingFlow";
import type { Profile } from "@/lib/types";

// Bridges the profile page (a server component) to OnboardingFlow (a
// client component) -- same pattern as OpenConversation.tsx bridges
// ChatShell. Reopening the same 4-step flow in edit mode, rather than a
// second editor, is the entire point of OnboardingFlow taking a `mode`
// prop in the first place.
export default function ProfileEditorButton({ profile, userEmail }: { profile: Profile; userEmail: string | null }) {
  const [editing, setEditing] = useState(false);
  const router = useRouter();

  return (
    <>
      <Button size="sm" onClick={() => setEditing(true)}>
        Edit preferences
      </Button>
      {editing && (
        <OnboardingFlow
          initialProfile={profile}
          userEmail={userEmail}
          mode="edit"
          onDone={() => {
            setEditing(false);
            router.refresh();
          }}
        />
      )}
    </>
  );
}
