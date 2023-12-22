import subprocess
from pathlib import Path
from typing import Annotated
from typing import cast
from typing import TypedDict

import cappa
from falco.utils import get_falco_blueprints_path
from falco.utils import run_shell_command
from falco.utils import simple_progress
from rich import print as rich_print

IMPORT_START_COMMENT = "# IMPORTS:START"
IMPORT_END_COMMENT = "# IMPORTS:END"
CODE_START_COMMENT = "# CODE:START"
CODE_END_COMMENT = "# CODE:END"


class PythonBlueprintContext(TypedDict):
    app_label: str
    model_name: str
    model_verbose_name_plural: str
    model_fields: dict[str, str]


class UrlsForContext(TypedDict):
    list_view_url: str
    create_view_url: str
    detail_view_url: str
    update_view_url: str
    delete_view_url: str


class HtmlBlueprintContext(PythonBlueprintContext, UrlsForContext):
    # a example of the dict: {"Name": "product.name", "Price": "{{product.price}}"}
    fields_verbose_name_with_accessor: dict[str, str]


class DjangoModel(TypedDict):
    name: str
    verbose_name_plural: str
    fields: dict[str, str]


models_data_code = """
from django.apps import apps
models = apps.get_app_config("{}").get_models()
exclude_fields = {}
get_name = lambda model: model.__name__
get_verbose_name_plural = lambda model: getattr(model._meta, 'verbose_name_plural', f"{{model.__name__}}s")
get_fields = lambda model: {{field.name: field.verbose_name for field in model._meta.fields if field.name not in exclude_fields}}
get_model_dict = lambda model: {{"name": get_name(model), "fields": get_fields(model), "verbose_name_plural": get_verbose_name_plural(model)}}
print([get_model_dict(model) for model in models])
"""

app_path_and_templates_dir_code = """
from django.apps import apps
from django.conf import settings
from pathlib import Path
app = apps.get_app_config("{}")
dirs = settings.TEMPLATES[0].get("DIRS", [])
templates_dir = Path(dirs[0]) if dirs else Path(app.path) / "templates"
app_templates_dir = templates_dir / "{}"
print((str(app.path), str(app_templates_dir)))
"""

django_render_template_code = """
from django.template.engine import Context, Template
print(Template('''{}''').render(Context({})))
"""


def extract_content_from(text: str, start_comment: str, end_comment: str):
    start_index = text.find(start_comment) + len(start_comment)
    end_index = text.find(end_comment)
    return text[start_index:end_index]


def get_urls(model_name_lower: str, urlsafe_model_verbose_name_plural: str) -> str:
    return f"""
        path('{urlsafe_model_verbose_name_plural}/', views.{model_name_lower}_list, name='{model_name_lower}_list'),
        path('{urlsafe_model_verbose_name_plural}/create/', views.{model_name_lower}_create, name='{model_name_lower}_create'),
        path('{urlsafe_model_verbose_name_plural}/<int:pk>/', views.{model_name_lower}_detail, name='{model_name_lower}_detail'),
        path('{urlsafe_model_verbose_name_plural}/<int:pk>/update/', views.{model_name_lower}_update, name='{model_name_lower}_update'),
        path('{urlsafe_model_verbose_name_plural}/<int:pk>/delete/', views.{model_name_lower}_delete, name='{model_name_lower}_delete'),
    """


def get_urls_template_string(app_label: str, model_name_lower: str) -> UrlsForContext:
    return {
        "list_view_url": f"{{% url '{app_label}:{model_name_lower}_list' %}}",
        "create_view_url": f"{{% url '{app_label}:{model_name_lower}_create' %}}",
        "detail_view_url": f"{{% url '{app_label}:{model_name_lower}_detail' {model_name_lower}.pk %}}",
        "update_view_url": f"{{% url '{app_label}:{model_name_lower}_update' {model_name_lower}.pk %}}",
        "delete_view_url": f"{{% url '{app_label}:{model_name_lower}_delete' {model_name_lower}.pk %}}",
    }


def render_to_string(template_content: str, context: dict):
    return run_shell_command(
        django_render_template_code.format(template_content, context),
        eval_result=False,
    )


@simple_progress("Running python formatters")
def run_python_formatters(filepath: str):
    autoflake = [
        "autoflake",
        "--in-place",
        "--remove-all-unused-imports",
        filepath,
    ]
    black = ["black", filepath]
    isort = ["isort", filepath]
    subprocess.run(autoflake, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(isort, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(black, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@simple_progress("Running html formatters")
def run_html_formatters(filepath: str):
    # djhtml = ["djhtml", filepath, "--tabwidth=4"]
    djlint = ["djlint", filepath, "--reformat"]
    # subprocess.run(djhtml, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(djlint, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get_blueprints_ending_in(file_ext: str) -> list[Path]:
    return [file for file in (get_falco_blueprints_path() / "crud").iterdir() if file.name.endswith(file_ext)]


def resolve_html_blueprints(user_blueprints_path: str | None) -> list[Path]:
    if user_blueprints_path:
        html_blueprints = [file for file in Path(user_blueprints_path).iterdir() if file.name.endswith(".html")]
        if not html_blueprints:
            raise cappa.Exit(f"No html blueprints found in {user_blueprints_path}", code=1)
    else:
        html_blueprints = get_blueprints_ending_in(".html")
    return html_blueprints


@cappa.command(help="Generate CRUD (Create, Read, Update, Delete) views for a model.", name="crud")
class ModelCRUD:
    model_path: Annotated[
        str,
        cappa.Arg(
            help="The path (<app_label>.<model name>) of the model to generate CRUD views for. Ex: myapp.product"
        ),
    ]
    blueprints: Annotated[
        str,
        cappa.Arg(
            default="",
            long="--blueprints",
            help="The path to custom html templates that will server as blueprints.",
        ),
    ]
    excluded_fields: Annotated[
        list[str],
        cappa.Arg(short=True, default=[], long="--exclude", help="Fields to exclude."),
    ]
    only_python: Annotated[
        bool,
        cappa.Arg(default=False, long="--only-python", help="Generate only python."),
    ]
    only_html: Annotated[bool, cappa.Arg(default=False, long="--only-html", help="Generate only html.")]
    entry_point: Annotated[
        bool,
        cappa.Arg(
            default=False,
            long="--entry-point",
            help="Use the specified model as the entry point of the app.",
        ),
    ]

    def __call__(self):
        v = self.model_path.split(".")
        if len(v) == 1:
            name = None
            app_label = v[0]
        else:
            name = v.pop()
            app_label = ".".join(v)

        if self.entry_point and not name:
            raise cappa.Exit("The --entry-point option requires a full model path.", code=1)

        with simple_progress("Getting models info"):
            all_django_models = cast(
                list[DjangoModel],
                run_shell_command(models_data_code.format(app_label, self.excluded_fields)),
            )

            app_folder_path, templates_dir = cast(
                tuple[str, str],
                run_shell_command(app_path_and_templates_dir_code.format(app_label, app_label)),
            )

            app_folder_path = Path(app_folder_path)
            templates_dir = Path(templates_dir)

        if name:
            for django_model in all_django_models:
                if django_model["name"].lower() == name.lower():
                    django_models = [django_model]
                    break
            else:
                raise cappa.Exit(f"Model {name} not found in app {app_label}", code=1)
        else:
            django_models = all_django_models

        python_blueprint_context: list[PythonBlueprintContext] = []
        html_blueprint_context: list[HtmlBlueprintContext] = []
        for django_model in django_models:
            python_blueprint_context.append(
                {
                    "app_label": app_label,
                    "model_name": django_model["name"],
                    "model_verbose_name_plural": django_model["verbose_name_plural"],
                    "model_fields": django_model["fields"],
                }
            )
            html_blueprint_context.append(
                {
                    "app_label": app_label,
                    "model_name": django_model["name"],
                    "model_verbose_name_plural": django_model["verbose_name_plural"],
                    "model_fields": django_model["fields"],
                    "fields_verbose_name_with_accessor": {
                        field_verbose_name: "{{" + f"{django_model['name'].lower()}.{field_name}" + "}}"
                        for field_name, field_verbose_name in django_model["fields"].items()
                    },
                    **get_urls_template_string(
                        app_label=app_label,
                        model_name_lower=django_model["name"].lower(),
                    ),
                }
            )

        python_blueprints = get_blueprints_ending_in(".py.bp")
        updated_python_files = set()

        if not self.only_html:
            updated_python_files.update(
                self.generate_python_code(
                    app_label=app_label,
                    blueprints=python_blueprints,
                    app_folder_path=app_folder_path,
                    contexts=python_blueprint_context,
                    entry_point=self.entry_point,
                )
            )

        html_blueprints = resolve_html_blueprints(self.blueprints)
        updated_html_files = set()
        if not self.only_python:
            updated_html_files.update(
                self.generate_html_templates(
                    contexts=html_blueprint_context,
                    entry_point=self.entry_point,
                    blueprints=html_blueprints,
                    templates_dir=templates_dir,
                )
            )

        for file in updated_python_files:
            run_python_formatters(str(file))

        for file in updated_html_files:
            run_html_formatters(str(file))

        display_names = ", ".join(m.get("name") for m in django_models)
        rich_print(f"[green] CRUD views generated for: {display_names}[/green]")

    @simple_progress("Generating python code")
    def generate_python_code(
        self,
        app_label: str,
        app_folder_path: Path,
        blueprints: list[Path],
        contexts: list[PythonBlueprintContext],
        entry_point: bool,
    ) -> list[Path]:
        updated_files = []
        # blueprints python files end in .py.bp
        for blueprint in blueprints:
            filecontent = blueprint.read_text()
            imports_template = extract_content_from(
                text=filecontent,
                start_comment=IMPORT_START_COMMENT,
                end_comment=IMPORT_END_COMMENT,
            )
            code_template = extract_content_from(
                text=filecontent,
                start_comment=CODE_START_COMMENT,
                end_comment=CODE_END_COMMENT,
            )
            file_name_without_bp = ".".join(blueprint.name.split(".")[:-1])
            file_to_write_to = app_folder_path / file_name_without_bp
            file_to_write_to.touch(exist_ok=True)

            imports_content = ""
            code_content = ""
            urls_content = ""

            for context in contexts:
                model_name_lower = context["model_name"].lower()
                imports_content += render_to_string(imports_template, context)
                code_content += render_to_string(code_template, context)
                urlsafe_model_verbose_name_plural = context["model_verbose_name_plural"].lower().replace(" ", "-")
                urls_content += get_urls(
                    model_name_lower=model_name_lower,
                    urlsafe_model_verbose_name_plural=urlsafe_model_verbose_name_plural,
                )
                if entry_point:
                    urls_content = urls_content.replace(f"{urlsafe_model_verbose_name_plural}/", "")
                    urls_content = urls_content.replace("list", "index")
                    urls_content = urls_content.replace(f"{model_name_lower}_", "")
                    code_content = code_content.replace(f"{model_name_lower}_", "")
                    code_content = code_content.replace("list", "index")

            file_to_write_to.write_text(imports_content + file_to_write_to.read_text() + code_content)
            updated_files.append(file_to_write_to)

        app_urls = app_folder_path / "urls.py"
        if app_urls.exists():
            urlpatterns = f"\nurlpatterns +=[{urls_content}]"
            app_urls.write_text(app_urls.read_text() + urlpatterns)
        else:
            app_urls.touch()
            app_urls.write_text(self._initial_urls_content(app_label, urls_content))
        updated_files.append(app_urls)
        return updated_files

    def _initial_urls_content(self, app_label: str, urls_content: str) -> str:
        return f"""
from django.urls import path
from . import views

app_name = "{app_label}"

urlpatterns = [
{urls_content}
]
        """

    @simple_progress("Generating html templates")
    def generate_html_templates(
        self,
        templates_dir: Path,
        blueprints: list[Path],
        contexts: list[HtmlBlueprintContext],
        entry_point: bool,
    ) -> list[Path]:
        updated_files = []
        templates_dir.mkdir(exist_ok=True, parents=True)
        for blueprint in blueprints:
            filecontent = blueprint.read_text()

            for context in contexts:
                model_name_lower = context["model_name"].lower()
                new_filename = f"{model_name_lower}_{blueprint.name}"
                if entry_point:
                    new_filename = blueprint.name
                if new_filename.startswith("list"):
                    new_filename = new_filename.replace("list", "index")
                file_to_write_to = templates_dir / new_filename
                file_to_write_to.touch(exist_ok=True)
                views_content = render_to_string(filecontent, context=context)
                views_content = self.patch_paginations_variables(
                    model_name_lower=model_name_lower, content=views_content
                )
                if entry_point:
                    views_content = views_content.replace(f"{model_name_lower}_", "")
                    views_content = views_content.replace("list", "index")
                file_to_write_to.write_text(views_content)
                updated_files.append(file_to_write_to)

        return updated_files

    def patch_paginations_variables(self, model_name_lower: str, content: str) -> str:
        # the pagination part is hard to get right even with using verbatim
        # this is a hack until I find a better solution
        conversion_map = {
            "products.has_previous": f"{model_name_lower}s.has_previous",
            "products.has_next": f"{model_name_lower}s.has_next",
            "products.paginator.page_range": f"{model_name_lower}s.paginator.page_range",
            "products.number": f"{model_name_lower}s.number",
            "products.next_page_number": f"{model_name_lower}s.next_page_number",
            "products.previous_page_number": f"{model_name_lower}s.previous_page_number",
            "products.num_pages": f"{model_name_lower}s.num_pages",
            "products.paginator.num_pages": f"{model_name_lower}s.paginator.num_pages",
            "for product in products": f"for {model_name_lower} in {model_name_lower}s",
        }
        for key, value in conversion_map.items():
            content = content.replace(key, value)
        return content
