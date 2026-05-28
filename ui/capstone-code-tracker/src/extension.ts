import * as vscode from "vscode";
import { createPatch } from "diff";

const previousTextByUri = new Map<string, string>();

export function activate(context: vscode.ExtensionContext) {
  const output = vscode.window.createOutputChannel("Capstone Code Tracker");

  output.appendLine("Capstone Code Tracker activated.");
  output.show(true);

  // Capture initial state of already open files.
  for (const document of vscode.workspace.textDocuments) {
    if (document.uri.scheme === "file") {
      previousTextByUri.set(document.uri.toString(), document.getText());
    }
  }

  const openListener = vscode.workspace.onDidOpenTextDocument((document) => {
    if (document.uri.scheme === "file") {
      previousTextByUri.set(document.uri.toString(), document.getText());
    }
  });

  const closeListener = vscode.workspace.onDidCloseTextDocument((document) => {
    previousTextByUri.delete(document.uri.toString());
  });

  const changeListener = vscode.workspace.onDidChangeTextDocument((event) => {
    if (event.contentChanges.length === 0) {
      return;
    }

    const document = event.document;

    if (document.uri.scheme !== "file") {
      return;
    }

    const uri = document.uri.toString();
    const before = previousTextByUri.get(uri) ?? "";
    const after = document.getText();

    const likelyPaste = event.contentChanges.some((change) => {
      return (
        change.text.length > 30 ||
        change.text.includes("\n") ||
        change.rangeLength > 30
      );
    });

    const patch = createPatch(
      document.fileName,
      before,
      after,
      "before",
      "after"
    );

    output.appendLine("=".repeat(80));
    output.appendLine(`File: ${document.fileName}`);
    output.appendLine(`Language: ${document.languageId}`);
    output.appendLine(`Version: ${document.version}`);
    output.appendLine(`Likely paste: ${likelyPaste}`);
    output.appendLine("");
    output.appendLine(patch);

    previousTextByUri.set(uri, after);
  });

  context.subscriptions.push(output, openListener, closeListener, changeListener);
}

export function deactivate() {}
