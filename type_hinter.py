#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import libcst as cst

TypeMap = dict[str, tuple[list[str], str]]


class StubParser(cst.CSTVisitor):
    def __init__(self):
        self.type_map: TypeMap = {}

    def visit_FunctionDef(self, node: cst.FunctionDef):
        ret_type = "Any"
        if node.returns and node.returns.annotation:
            ret_type = cst.Module([]).code_for_node(node.returns.annotation)
        param_types = []
        for param in node.params.params:
            if param.annotation:
                param_types.append(cst.Module([]).code_for_node(param.annotation))
            else:
                param_types.append("Any")
        if node.params.star_arg and node.params.star_arg.annotation:
            param_types.append(
                cst.Module([]).code_for_node(node.params.star_arg.annotation)
            )
        if node.params.star_kwarg and node.params.star_kwarg.annotation:
            param_types.append(
                cst.Module([]).code_for_node(node.params.star_kwarg.annotation)
            )
        self.type_map[node.name.value] = (param_types, ret_type)


class TypeInjector(cst.CSTTransformer):
    def __init__(self, type_map: TypeMap):
        self.type_map = type_map

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        func_name = updated_node.name.value
        if func_name not in self.type_map:
            return updated_node
        param_types, ret_type = self.type_map[func_name]
        if updated_node.returns is None:
            updated_node = updated_node.with_changes(
                returns=cst.Annotation(annotation=cst.parse_expression(ret_type))
            )
        params = updated_node.params
        new_params_list = []
        for i, param in enumerate(params.params):
            if i < len(param_types) and param.annotation is None:
                new_param = param.with_changes(
                    annotation=cst.Annotation(
                        annotation=cst.parse_expression(param_types[i])
                    )
                )
                new_params_list.append(new_param)
            else:
                new_params_list.append(param)
        updated_node = updated_node.with_changes(
            params=params.with_changes(params=new_params_list)
        )
        return updated_node


def run_stubgen(path: str) -> str:
    out_dir = "stubgen_out"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    subprocess.run(["stubgen", "-o", out_dir, path], check=True, capture_output=True)
    base_name = os.path.basename(path).replace(".py", ".pyi")
    pyi_path = os.path.join(out_dir, base_name)
    return pyi_path


def process_file(path: str):
    try:
        pyi_path = run_stubgen(path)
    except subprocess.CalledProcessError as e:
        print(f"Stubgen failed: {e}")
        return
    with open(pyi_path, "r") as f:
        pyi_code = f.read()
    pyi_module = cst.parse_module(pyi_code)
    stub_parser = StubParser()
    pyi_module.visit(stub_parser)
    type_map = stub_parser.type_map
    with open(path, "r") as f:
        source_code = f.read()
    module = cst.parse_module(source_code)
    transformer = TypeInjector(type_map)
    modified_module = module.visit(transformer)
    with open(path, "w") as f:
        f.write(modified_module.code)
    shutil.rmtree("stubgen_out")
    print(f"Successfully annotated {path} using mypy stubs.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <python_file>")
        sys.exit(1)
    process_file(sys.argv[1])
