"use client";

import { useState } from "react";
import type { TreeNode } from "../../lib/api";

type Props = {
  nodes: TreeNode[];
  selectedPath: string | null;
  onOpen: (path: string) => void;
};

function NodeRow({
  node,
  depth,
  selectedPath,
  onOpen,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  onOpen: (path: string) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  const isDir = node.type === "directory";
  const selected = selectedPath === node.path;

  return (
    <div className="tree-node">
      <button
        type="button"
        className={`tree-row ${selected ? "selected" : ""}`}
        style={{ paddingLeft: 8 + depth * 12 }}
        onClick={() => {
          if (isDir) setOpen((value) => !value);
          else onOpen(node.path);
        }}
      >
        <span className="tree-icon">{isDir ? (open ? "▾" : "▸") : "·"}</span>
        <span className="tree-name">{node.name}</span>
      </button>
      {isDir && open && node.children?.map((child) => (
        <NodeRow
          key={child.path}
          node={child}
          depth={depth + 1}
          selectedPath={selectedPath}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

export function FileTree({ nodes, selectedPath, onOpen }: Props) {
  if (nodes.length === 0) {
    return <p className="panel-muted">No files in this workspace.</p>;
  }
  return (
    <div className="file-tree">
      {nodes.map((node) => (
        <NodeRow key={node.path} node={node} depth={0} selectedPath={selectedPath} onOpen={onOpen} />
      ))}
    </div>
  );
}
