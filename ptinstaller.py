# code: utf-8
"""
Client program to help install tools announced on the Pythonista Tools GitHub repo.
"""
import os
import sys
import requests
import urlparse
import re
import functools
import shutil
import json
import zipfile

try:
    import ui
    import console
    import webbrowser
except ImportError:
    import dummyui as ui
    import dummyconsole as console

__version__ = '1.0.0'


class InvalidGistURLError(Exception):
    pass

class MultipleFilesInGistError(Exception):
    pass

class NoFilesInGistError(Exception):
    pass

class GistDownloadError(Exception):
    pass


class GitHubAPI(object):
    API_URL = 'https://api.github.com'

    @staticmethod
    def contents(owner, repo):
        r = requests.get(urlparse.urljoin(GitHubAPI.API_URL, 'repos/{}/{}/contents'.format(owner, repo)))
        return r.json()


class PythonistaToolsRepo(object):
    """
    Manage and gather information from the Pythonista Tools repo.
    """

    PATTERN_NAME_URL_DESCRIPTION = re.compile(r'^\| +\[([^]]+)\] *\[([^]]*)\][^|]+\| (.*) \|', re.MULTILINE)
    PATTERN_NAME_URL = re.compile(r'^\[([^]]+)\]: *(.*)', re.MULTILINE)

    def __init__(self):
        self.owner = 'Pythonista-Tools'
        self.repo = 'Pythonista-Tools'

        self.cached_tools_dict = {}

    def get_categories(self):
        """
        Get URL of all the markdown files that list Pythonista tools of different categories.
        """
        categories = {}
        for content in GitHubAPI.contents(self.owner, self.repo):
            name = content['name']
            if name.endswith('.md') and name not in ['README.md']:
                categories[os.path.splitext(name)[0]] = {'url': content['download_url'],
                                                         'sha': content['sha']}
        return categories

    def get_tools_from_md(self, url):
        """
        Retrieve markdown file from the given URL and parse its content to build a dict
        of tools.
        :return:
        """
        # If results are available in the cache, avoid hitting the web
        if url in self.cached_tools_dict:
            return self.cached_tools_dict[url]

        md = requests.get(url).text
        # Find all script name and its url
        tools_dict = {}
        for name, url, description in self.PATTERN_NAME_URL_DESCRIPTION.findall(md):
            tools_dict[name] = {'url': url, 'description': description.strip()}

        for name, url in self.PATTERN_NAME_URL.findall(md):
            if name in tools_dict:
                tools_dict[name]['url'] = url
            else:
                for tool_name, tool_content in tools_dict.items():
                    if tool_content['url'] == name:
                        tool_content['url'] = url
                    if tool_content['description'] == '[%s]' % name:
                        tool_content['description'] = url

        # Filter out tools that has no download url
        self.cached_tools_dict[url] = {k: v for k, v in tools_dict.items() if v['url']}

        return self.cached_tools_dict[url]


class GitHubRepoInstaller(object):

    PATTERN_USER_REPO = r'^https?://github.com/(.+)/(.+)'

    @staticmethod
    def get_github_user_repo(url):
        m = re.match(GitHubRepoInstaller.PATTERN_USER_REPO, url)
        return m.groups if m else None

    def download(self, url):
        user_name, repo_name = self.get_github_user_repo(url)
        zipfile_url = urlparse.urljoin(url, '%s/%s/archive/master.zip' % (user_name, repo_name))
        tmp_zipfile = os.path.join(os.environ['TMPDIR'], '%s-master.zip' % repo_name)

        r = requests.get(zipfile_url)
        with open(tmp_zipfile, 'wb') as outs:
            outs.write(r.content)

        return tmp_zipfile

    def install(self, url, target_folder):

        tmp_zipfile = self.download(url)
        if tmp_zipfile:
            base_dir = os.path.splitext(os.path.basename(tmp_zipfile))[0] + '/'
            with open(tmp_zipfile, 'rb') as ins:
                zipfp = zipfile.ZipFile(ins)
                for name in zipfp.namelist():
                    data = zipfp.read(name)
                    name = name.split(base_dir, 1)[-1]  # strip the top-level target_folder
                    if name == '':  # skip top-level target_folder
                        continue

                    fname = os.path.join(target_folder, name)
                    if fname.endswith('/'):  # A target_folder
                        if not os.path.exists(fname):
                            os.makedirs(fname)
                    else:
                        fp = open(fname, 'wb')
                        try:
                            fp.write(data)
                        finally:
                            fp.close()


class GistInstaller(object):
    PATTERN_GIST_ID = r'http(s?)://gist.github.com/([0-9a-zA-Z]*)/([0-9a-f]*)'

    @staticmethod
    def get_gist_id(url):
        m = re.match(GistInstaller.PATTERN_GIST_ID, url)
        return m.group(3) if m else None

    def download(self, url):
        gist_id = self.get_gist_id(url)
        if gist_id:
            json_url = 'https://api.github.com/gists/' + gist_id
            try:
                gist_json = requests.get(json_url).text
                gist_info = json.loads(gist_json)
                files = gist_info['files']
            except:
                raise GistDownloadError()
            py_files = []
            for file_info in files.values():
                lang = file_info.get('language', None)
                if lang != 'Python':
                    continue
                py_files.append(file_info)
            if len(py_files) > 1:
                raise MultipleFilesInGistError()
            elif len(py_files) == 0:
                raise NoFilesInGistError()
            else:
                file_info = py_files[0]
                filename = file_info['filename']
                content = file_info['content']
                return filename, content
        else:
            raise InvalidGistURLError()

    def install(self, url, target_folder):
        filename, content = self.download(url)
        with open(os.path.join(target_folder, filename), 'w') as outs:
            outs.write(content)


class ToolsTable(object):
    def __init__(self, app, category_name, category_url):
        self.app = app
        self.category_name = category_name
        self.category_url = category_url
        self.view = ui.TableView(frame=(0, 0, 640, 640))
        self.view.name = category_name

        self.tools_dict = self.app.repo.get_tools_from_md(category_url)
        self.tool_names = sorted(self.tools_dict.keys())

        self.view.data_source = self
        self.view.delegate = self

    def tableview_number_of_sections(self, tableview):
        return 1

    def tableview_number_of_rows(self, tableview, section):
        return len(self.tools_dict)

    def tableview_cell_for_row(self, tableview, section, row):

        cell = ui.TableViewCell('subtitle')
        tool_name = self.tool_names[row]
        tool_url = self.tools_dict[tool_name]['url']
        cell.text_label.text = tool_name
        cell.detail_text_label.text = self.tools_dict[tool_name]['description']
        if self.app.is_tool_installed(self.category_name, tool_name):
            btn = ui.Button(title='  Uninstall  ')
            btn.action = functools.partial(self.app.uninstall,
                                           self.category_name,
                                           tool_name,
                                           tool_url)
        else:
            btn = ui.Button(title='  Install  ')
            btn.action = functools.partial(self.app.install,
                                           self.category_name,
                                           tool_name,
                                           tool_url)
        cell.content_view.add_subview(btn)
        btn.font = ('Helvetica', 12)
        btn.background_color = 'white'
        btn.tint_color = 'blue'
        btn.border_width = 1
        btn.border_color = 'green'
        btn.corner_radius = 5
        btn.font = (btn.font[0], 18)
        btn.size_to_fit()
        btn.x = self.app.nav_view.width - btn.width - 20
        btn.y = (cell.height - btn.height) / 2

        return cell

    def tableview_can_delete(self, tableview, section, row):
        return False

    def tableview_can_move(self, tableview, section, row):
        return False


class CategoriesTable(object):
    def __init__(self, app):
        self.app = app
        self.view = ui.TableView(frame=(0, 0, 640, 640))
        self.view.name = 'Categories'

        self.categories_dict = self.app.repo.get_categories()

        categories_listdatasource = ui.ListDataSource(
            {'title': category_name, 'accessory_type': 'disclosure_indicator'}
            for category_name in sorted(self.categories_dict.keys())
        )
        categories_listdatasource.action = self.category_item_tapped

        self.view.data_source = categories_listdatasource
        self.view.delegate = categories_listdatasource

    def category_item_tapped(self, sender):
        category_name = sender.items[sender.selected_row]['title']
        category_url = self.categories_dict[category_name]['url']
        tools_table = ToolsTable(self.app, category_name, category_url)
        self.app.nav_view.push_view(tools_table.view)


class PythonistaToolsInstaller(object):
    INSTALLATION_ROOT = os.path.expanduser('~/Documents/bin')

    def __init__(self):
        self.repo = PythonistaToolsRepo()
        self.github_installer = GitHubRepoInstaller()
        self.gist_installer = GistInstaller()
        categories_table = CategoriesTable(self)

        self.nav_view = ui.NavigationView(categories_table.view)
        self.nav_view.name = 'Pythonista Tools Installer'

    def repo_type(self, url):
        re.compile(r'^http(s?)://gist.github.com/')

    @staticmethod
    def get_target_folder(category_name, tool_name):
        return os.path.join(PythonistaToolsInstaller.INSTALLATION_ROOT, category_name, tool_name)

    @staticmethod
    def is_tool_installed(category_name, tool_name):
        return os.path.exists(PythonistaToolsInstaller.get_target_folder(category_name, tool_name))

    def install(self, category_name, tool_name, tool_url, sender):
        sender.title = '  Loading  '
        sender.size_to_fit()
        target_folder = PythonistaToolsInstaller.get_target_folder(category_name, tool_name)
        if not os.path.exists(target_folder):
            os.makedirs(target_folder)

        self._install(category_name, tool_name, tool_url, target_folder, sender)

    @ui.in_background
    def _install(self, category_name, tool_name, tool_url, target_folder, sender):
        try:
            if self.gist_installer.get_gist_id(tool_url):
                self.gist_installer.install(tool_url, target_folder)
            elif self.github_installer.get_github_user_repo(tool_url):
                self.github_installer.install(tool_url, target_folder)
            else:  # any other url types, including iTunes
                webbrowser.open(tool_url)
            sender.title = '  Uninstall  '
            sender.action = functools.partial(self.uninstall,
                                              category_name, tool_name, tool_url)
            sender.size_to_fit()
            console.hud_alert('%s installed' % tool_name, 'success', 1.0)
        except Exception as e:
            sys.stderr.write('%s\n' % repr(e))
            console.hud_alert('Installation failed', 'error', 1.0)

    def uninstall(self, category_name, tool_name, tool_url, sender):
        target_folder = PythonistaToolsInstaller.get_target_folder(category_name, tool_name)
        if os.path.exists(target_folder):
            shutil.rmtree(target_folder)
        sender.title = '  Install  '
        sender.action = functools.partial(self.install,
                                          category_name, tool_name, tool_url)
        sender.size_to_fit()
        console.hud_alert('%s uninstalled' % tool_name, 'success', 1.0)

    def launch(self):
        self.nav_view.present('fullscreen')


if __name__ == '__main__':
    ptinstaller = PythonistaToolsInstaller()
    ptinstaller.launch()
