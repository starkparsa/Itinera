"use client";

import { useState } from "react";
import { deleteAccount } from "@/lib/backend";
import { signOutAction } from "@/lib/authActions";
import { useToast } from "@/components/ui/toast";
import { buttonVariants } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

/** Danger-zone action on the profile page -- irreversible, same
 * confirm-before-destroy pattern as Sidebar.tsx's delete-chat dialog.
 * On success, signs the user out immediately (their session JWT would
 * otherwise keep "working" in the sense of passing signature
 * verification, even though every backend call now 401s/404s against a
 * user row that no longer exists -- staying logged in client-side would
 * be misleading). On failure, surfaces the real error via toast and
 * leaves the account untouched. */
export default function DeleteAccountButton() {
  const { toast } = useToast();
  const [isDeleting, setIsDeleting] = useState(false);

  async function handleConfirm() {
    setIsDeleting(true);
    const result = await deleteAccount();
    if (!result.ok) {
      setIsDeleting(false);
      toast({ title: "Couldn't delete your account", description: result.error, variant: "destructive" });
      return;
    }
    await signOutAction();
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger
        className={buttonVariants({ variant: "outline", size: "sm", className: "text-destructive hover:text-destructive" })}
      >
        Delete account
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete your account?</AlertDialogTitle>
          <AlertDialogDescription>
            Your account, every trip you&apos;ve planned, your chat history, your profile answers, and your
            passport stamps will all be permanently deleted. This can&apos;t be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={handleConfirm} disabled={isDeleting}>
            {isDeleting ? "Deleting…" : "Delete account"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
