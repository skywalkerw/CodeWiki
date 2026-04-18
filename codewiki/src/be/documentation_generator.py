import logging
import os
import json
import re
from typing import Dict, List, Any, Optional
from copy import deepcopy
import traceback

# Configure logging and monitoring
logger = logging.getLogger(__name__)

# Parent/repo overview: retry when <OVERVIEW> is missing or empty (override via env)
_OVERVIEW_MAX_ATTEMPTS = max(1, int(os.environ.get("CODEWIKI_OVERVIEW_MAX_ATTEMPTS", "3")))


def _doc_lang_is_zh(doc_language: Optional[str]) -> bool:
    s = (doc_language or "en").strip().lower().replace("_", "-")
    return s in ("zh", "zh-cn", "cn")


def _try_parse_overview_tags(raw: str) -> Optional[str]:
    """Return markdown inside ``<OVERVIEW>...</OVERVIEW>`` if present and non-empty; else None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    if "<OVERVIEW>" in text and "</OVERVIEW>" in text:
        try:
            inner = text.split("<OVERVIEW>", 1)[1].split("</OVERVIEW>", 1)[0].strip()
            if inner:
                return inner
        except IndexError:
            pass

    m = re.search(r"<overview>\s*(.*?)\s*</overview>", text, re.IGNORECASE | re.DOTALL)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


def _overview_retry_addendum(previous_response: str, attempt_number: int, doc_language: Optional[str]) -> str:
    """Instructions appended to the original prompt so the model fixes the format."""
    snippet = previous_response.strip()
    if len(snippet) > 2000:
        snippet = snippet[:2000] + "\n... [truncated] ..."

    if _doc_lang_is_zh(doc_language):
        return f"""

---
【格式错误 — 第 {attempt_number} 次重试】
你的上一次回复**不符合要求**：必须输出一对标签 `<OVERVIEW>` 与 `</OVERVIEW>`（大小写一致），且标签内必须是**非空**的 Markdown 正文。

请根据**同样的任务说明与上文给出的 REPO_STRUCTURE**，**完整重新生成**一份答案；不要只道歉或只输出一句话，并确保整篇文档正文都写在 `<OVERVIEW>` 与 `</OVERVIEW>` 之间。

你上一次的回复如下（供对照，请修正格式后重新输出全文）：
```
{snippet}
```
"""

    return f"""

---
[FORMAT ERROR — retry {attempt_number}]
Your previous reply was INVALID: you must output exactly one pair of tags `<OVERVIEW>` and `</OVERVIEW>` (case-sensitive), with non-empty Markdown **between** them.

Regenerate the **full** answer for the same task and REPO_STRUCTURE data above. Do not reply with only an apology or a single line.

Your previous reply (for reference; fix and output the complete valid response):
```
{snippet}
```
"""


def _extract_overview_from_llm_response(raw: str, module_name: str) -> str:
    """
    Last-resort: use full model output when tags are still missing after retries.
    """
    if raw is None:
        raise ValueError("Empty LLM response for overview")
    text = str(raw).strip()
    if not text:
        raise ValueError("Empty LLM response for overview")

    parsed = _try_parse_overview_tags(text)
    if parsed is not None:
        return parsed

    logger.warning(
        "Overview response for %r still missing valid <OVERVIEW> tags after retries; saving full output (%d chars).",
        module_name,
        len(text),
    )
    return text


# Local imports
from codewiki.src.be.dependency_analyzer import DependencyGraphBuilder
from codewiki.src.be.llm_services import call_llm
from codewiki.src.be.prompt_template import (
    format_module_overview_prompt,
    format_repo_overview_prompt,
)
from codewiki.src.be.cluster_modules import cluster_modules
from codewiki.src.config import (
    Config,
    FIRST_MODULE_TREE_FILENAME,
    MODULE_TREE_FILENAME,
    OVERVIEW_FILENAME
)
from codewiki.src.utils import file_manager
from codewiki.src.be.agent_orchestrator import AgentOrchestrator


class DocumentationGenerator:
    """Main documentation generation orchestrator."""
    
    def __init__(self, config: Config, commit_id: str = None):
        self.config = config
        self.commit_id = commit_id
        self.graph_builder = DependencyGraphBuilder(config)
        self.agent_orchestrator = AgentOrchestrator(config)
    
    def create_documentation_metadata(self, working_dir: str, components: Dict[str, Any], num_leaf_nodes: int):
        """Create a metadata file with documentation generation information."""
        from datetime import datetime
        
        metadata = {
            "generation_info": {
                "timestamp": datetime.now().isoformat(),
                "main_model": self.config.main_model,
                "generator_version": "1.0.1",
                "repo_path": self.config.repo_path,
                "commit_id": self.commit_id
            },
            "statistics": {
                "total_components": len(components),
                "leaf_nodes": num_leaf_nodes,
                "max_depth": self.config.max_depth
            },
            "files_generated": [
                "overview.md",
                "module_tree.json",
                "first_module_tree.json"
            ]
        }
        
        # Add generated markdown files to the metadata
        try:
            for file_path in os.listdir(working_dir):
                if file_path.endswith('.md') and file_path not in metadata["files_generated"]:
                    metadata["files_generated"].append(file_path)
        except Exception as e:
            logger.warning(f"Could not list generated files: {e}")
        
        metadata_path = os.path.join(working_dir, "metadata.json")
        file_manager.save_json(metadata, metadata_path)

    
    def get_processing_order(self, module_tree: Dict[str, Any], parent_path: List[str] = []) -> List[tuple[List[str], str]]:
        """Get the processing order using topological sort (leaf modules first)."""
        processing_order = []
        
        def collect_modules(tree: Dict[str, Any], path: List[str]):
            for module_name, module_info in tree.items():
                current_path = path + [module_name]
                
                # If this module has children, process them first
                if module_info.get("children") and isinstance(module_info["children"], dict) and module_info["children"]:
                    collect_modules(module_info["children"], current_path)
                    # Add this parent module after its children
                    processing_order.append((current_path, module_name))
                else:
                    # This is a leaf module, add it immediately
                    processing_order.append((current_path, module_name))
        
        collect_modules(module_tree, parent_path)
        return processing_order

    def is_leaf_module(self, module_info: Dict[str, Any]) -> bool:
        """Check if a module is a leaf module (has no children or empty children)."""
        children = module_info.get("children", {})
        return not children or (isinstance(children, dict) and len(children) == 0)

    def build_overview_structure(self, module_tree: Dict[str, Any], module_path: List[str],
                                 working_dir: str) -> Dict[str, Any]:
        """Build structure for overview generation with 1-depth children docs and target indicator."""
        
        processed_module_tree = deepcopy(module_tree)
        module_info = processed_module_tree
        for path_part in module_path:
            module_info = module_info[path_part]
            if path_part != module_path[-1]:
                module_info = module_info.get("children", {})
            else:
                module_info["is_target_for_overview_generation"] = True

        if "children" in module_info:
            module_info = module_info["children"]

        for child_name, child_info in module_info.items():
            if os.path.exists(os.path.join(working_dir, f"{child_name}.md")):
                child_info["docs"] = file_manager.load_text(os.path.join(working_dir, f"{child_name}.md"))
            else:
                logger.warning(f"Module docs not found at {os.path.join(working_dir, f"{child_name}.md")}")
                child_info["docs"] = ""

        return processed_module_tree

    async def generate_module_documentation(self, components: Dict[str, Any], leaf_nodes: List[str]) -> str:
        """Generate documentation for all modules using dynamic programming approach."""
        # Prepare output directory
        working_dir = os.path.abspath(self.config.docs_dir)
        file_manager.ensure_directory(working_dir)

        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        first_module_tree_path = os.path.join(working_dir, FIRST_MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)
        first_module_tree = file_manager.load_json(first_module_tree_path)
        
        # Get processing order (leaf modules first)
        processing_order = self.get_processing_order(first_module_tree)

        
        # Process modules in dependency order
        final_module_tree = module_tree
        processed_modules = set()

        if len(module_tree) > 0:
            for module_path, module_name in processing_order:
                try:
                    # Reload module tree to get latest hierarchical structure from sub-agent modifications
                    module_tree = file_manager.load_json(module_tree_path)
                    
                    # Get the module info from the tree
                    module_info = module_tree
                    for path_part in module_path:
                        module_info = module_info[path_part]
                        if path_part != module_path[-1]:  # Not the last part
                            module_info = module_info.get("children", {})
                    
                    # Skip if already processed
                    module_key = "/".join(module_path)
                    if module_key in processed_modules:
                        continue
                    
                    # Process the module
                    if self.is_leaf_module(module_info):
                        logger.info(f"📄 Processing leaf module: {module_key}")
                        final_module_tree = await self.agent_orchestrator.process_module(
                            module_name, components, module_info["components"], module_path, working_dir
                        )
                    else:
                        logger.info(f"📁 Processing parent module: {module_key}")
                        final_module_tree = await self.generate_parent_module_docs(
                            module_path, working_dir
                        )
                    
                    processed_modules.add(module_key)
                    
                except Exception as e:
                    logger.error(f"Failed to process module {module_key}: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    continue

            # Generate repo overview
            logger.info(f"📚 Generating repository overview")
            final_module_tree = await self.generate_parent_module_docs(
                [], working_dir
            )
        else:
            logger.info(f"Processing whole repo because repo can fit in the context window")
            repo_name = os.path.basename(os.path.normpath(self.config.repo_path))
            final_module_tree = await self.agent_orchestrator.process_module(
                repo_name, components, leaf_nodes, [], working_dir
            )

            # save final_module_tree to module_tree.json
            file_manager.save_json(final_module_tree, os.path.join(working_dir, MODULE_TREE_FILENAME))

            # rename repo_name.md to overview.md
            repo_overview_path = os.path.join(working_dir, f"{repo_name}.md")
            if os.path.exists(repo_overview_path):
                os.rename(repo_overview_path, os.path.join(working_dir, OVERVIEW_FILENAME))
        
        return working_dir

    async def generate_parent_module_docs(self, module_path: List[str], 
                                        working_dir: str) -> Dict[str, Any]:
        """Generate documentation for a parent module based on its children's documentation."""
        module_name = module_path[-1] if len(module_path) >= 1 else os.path.basename(os.path.normpath(self.config.repo_path))

        logger.info(f"Generating parent documentation for: {module_name}")
        
        # Load module tree
        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)

        # check if overview docs already exists
        overview_docs_path = os.path.join(working_dir, OVERVIEW_FILENAME)
        if os.path.exists(overview_docs_path):
            logger.info(f"✓ Overview docs already exists at {overview_docs_path}")
            return module_tree

        # check if parent docs already exists
        parent_docs_path = os.path.join(working_dir, f"{module_name if len(module_path) >= 1 else OVERVIEW_FILENAME.replace('.md', '')}.md")
        if os.path.exists(parent_docs_path):
            logger.info(f"✓ Parent docs already exists at {parent_docs_path}")
            return module_tree

        # Create repo structure with 1-depth children docs and target indicator
        repo_structure = self.build_overview_structure(module_tree, module_path, working_dir)

        rs = json.dumps(repo_structure, indent=4)
        lang = getattr(self.config, "doc_language", "en")
        prompt = (
            format_module_overview_prompt(module_name, rs, lang)
            if len(module_path) >= 1
            else format_repo_overview_prompt(module_name, rs, lang)
        )
        
        try:
            parent_docs: Optional[str] = None
            parent_content: Optional[str] = None
            current_prompt = prompt

            for attempt in range(_OVERVIEW_MAX_ATTEMPTS):
                parent_docs = call_llm(current_prompt, self.config)
                parsed = _try_parse_overview_tags(parent_docs)
                if parsed is not None:
                    parent_content = parsed
                    if attempt > 0:
                        logger.info(
                            "Overview for %r: valid <OVERVIEW> after %d retry attempt(s).",
                            module_name,
                            attempt,
                        )
                    break
                if attempt + 1 < _OVERVIEW_MAX_ATTEMPTS:
                    logger.warning(
                        "Overview for %r: missing or empty <OVERVIEW> (attempt %d/%d); retrying with format hint.",
                        module_name,
                        attempt + 1,
                        _OVERVIEW_MAX_ATTEMPTS,
                    )
                    current_prompt = prompt + _overview_retry_addendum(
                        parent_docs or "", attempt + 1, lang
                    )
                else:
                    parent_content = _extract_overview_from_llm_response(parent_docs, module_name)

            if parent_content is None:
                parent_content = _extract_overview_from_llm_response(parent_docs, module_name)

            file_manager.save_text(parent_content, parent_docs_path)

            logger.debug(f"Successfully generated parent documentation for: {module_name}")
            return module_tree

        except Exception as e:
            logger.error(f"Error generating parent documentation for {module_name}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    async def run(self) -> None:
        """Run the complete documentation generation process using dynamic programming."""
        try:
            # Build dependency graph
            components, leaf_nodes = self.graph_builder.build_dependency_graph()

            logger.debug(f"Found {len(leaf_nodes)} leaf nodes")
            # logger.debug(f"Leaf nodes:\n{'\n'.join(sorted(leaf_nodes)[:200])}")
            # exit()
            
            # Cluster modules
            working_dir = os.path.abspath(self.config.docs_dir)
            file_manager.ensure_directory(working_dir)
            first_module_tree_path = os.path.join(working_dir, FIRST_MODULE_TREE_FILENAME)
            module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
            
            # Check if module tree exists
            if os.path.exists(first_module_tree_path):
                logger.debug(f"Module tree found at {first_module_tree_path}")
                module_tree = file_manager.load_json(first_module_tree_path)
            else:
                logger.debug(f"Module tree not found at {module_tree_path}, clustering modules")
                module_tree = cluster_modules(leaf_nodes, components, self.config)
                file_manager.save_json(module_tree, first_module_tree_path)
            
            file_manager.save_json(module_tree, module_tree_path)
            
            logger.debug(f"Grouped components into {len(module_tree)} modules")
            
            # Generate module documentation using dynamic programming approach
            # This processes leaf modules first, then parent modules
            working_dir = await self.generate_module_documentation(components, leaf_nodes)
            
            # Create documentation metadata
            self.create_documentation_metadata(working_dir, components, len(leaf_nodes))
            
            logger.debug(f"Documentation generation completed successfully using dynamic programming!")
            logger.debug(f"Processing order: leaf modules → parent modules → repository overview")
            logger.debug(f"Documentation saved to: {working_dir}")
            
        except Exception as e:
            logger.error(f"Documentation generation failed: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise