"use client"

import * as vscode from 'vscode';
// this is required syntax highlighting
import '@codingame/monaco-vscode-python-default-extension';
import { RegisteredFileSystemProvider, registerFileSystemOverlay, RegisteredMemoryFile } from '@codingame/monaco-vscode-files-service-override';
import { MonacoEditorLanguageClientWrapper } from 'monaco-editor-wrapper';
import { useWorkerFactory } from 'monaco-editor-wrapper/workerFactory';
import { createUserConfig } from './config';
import { useEffect, useRef } from 'react';

const configureMonacoWorkers = () => {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useWorkerFactory({
        ignoreMapping: true,
        workerLoaders: {
            editorWorkerService: () => new Worker(new URL('monaco-editor/esm/vs/editor/editor.worker.js', import.meta.url), { type: 'module' }),
        }
    });
};

configureMonacoWorkers();

export default function Editor() {
  const editorContainer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Note: can't get C++ working. might need to register cpp file extension?
    // const userConfig = createUserConfig('/workspace', "hello", '/workspace/hello.py');
    const userConfig = createUserConfig('/workspace', "hello", '/workspace/hello.cpp');
    const wrapper = new MonacoEditorLanguageClientWrapper();

    (async () => {
      await wrapper.init(userConfig);
      await wrapper.start(editorContainer.current);
    })();

    return () => {
      wrapper.dispose();
    };
  }, []);
  
  return (
    <div ref={editorContainer} className="h-screen" />
  );
}
