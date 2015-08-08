#! /usr/bin/env python3

# TODO:
#   fix handling of dashes/underscores in config keys

import os
import collections

import configargparse
import configfile

class ConfigFileParser:

    def __init__(self, top_level_arg, subname=None):
        self.top_level_arg = top_level_arg
        self.subname = subname

    def parse(self, stream, context=None):
        """
        Parses a config file and returns a dictionary of settings
        """
        cf = configfile.ConfigFile(stream, inherit_options=True, section_fallback=True)

        try:
            _arg = "--" + self.top_level_arg
            _i = context.index(_arg)
            top_level = context[_i]
        except (ValueError, IndexError):
            top_level = None

        if top_level is None:
            top_level = cf[self.top_level_arg]
            if not top_level:
                raise coonfigargparse.ConfigFileParserException("top-level parameter '{}' not found")
        return cf(top_level)(self.subname).get_options()

    def serialize(self, items):
        """Does the inverse of config parsing by taking parsed values and
        converting them back to a string representing config file contents.

        Args:
            items: an OrderedDict with items to be written to the config file
        Returns:
            contents of config file as a string
        """
        pass

    def get_syntax_description(self):
        return ""

class Defaults(collections.UserDict):
    def __init__(self):
        super().__init__()
        project_name = "wiki-scripts"

        # global arguments
        config_dir = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        self.data["config"] = os.path.join(config_dir, "{0}/{0}.conf".format(project_name))

        cache_dir = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
        self.data["cache_dir"] = os.path.join(cache_dir, project_name)

        self.data["tmp_dir"] = os.path.join("/tmp", project_name)

        # ArchWiki specifics
        self.data["site"] = "ArchWiki"
        # NOTE: These depend on site=ArchWiki, but (config)argparse does not support conditional defaults
        # TODO: document the behaviour properly; also emphasize that --help does not
        #       take defaults from the config file (which is just right)
        self.data["api_url"] = "https://wiki.archlinux.org/api.php"
        self.data["index_url"] = "https://wiki.archlinux.org/index.php"

# any path, the dirname part must exist (e.g. path to a file that will be created in the future)
def argtype_dirname_must_exist(string):
    dirname, _ = os.path.split(os.path.abspath(string))
    if not os.path.isdir(dirname):
        raise configargparse.ArgumentTypeError("directory '%s' does not exist" % dirname)
    return string

# path to existing directory
def argtype_existing_dir(string):
    if not os.path.isdir(string):
        raise configargparse.ArgumentTypeError("directory '%s' does not exist" % string)
    return string

def getArgParser(name, *args, **kwargs):
    # create config file parser
    cfp = ConfigFileParser("site", name)
    kwargs["config_file_parser"] = cfp
    kwargs["ignore_unknown_config_file_keys"] = True

    # set brief usage parameter by default
    kwargs.setdefault("usage", "%(prog)s [options]")
    # TODO: the supplied description is merged with the one from configargparse, which looks very ugly

    ap = configargparse.ArgParser(*args, **kwargs)

    # add config file and site arguments
    ap.add_argument("-c", "--config", metavar="PATH", is_config_file_arg=True,
            help="path to config file (default: %(default)s)")
    ap.add_argument("--site",
            help="sets the top-level section to be read from config files (default: %(default)s)")

    # add other global arguments
    ap.add_argument("--tmp-dir", type=argtype_dirname_must_exist, metavar="PATH",
            help="temporary directory path (will be created if necessary, but parent directory must exist) (default: %(default)s)")
    ap.add_argument("--cache-dir", type=argtype_dirname_must_exist, metavar="PATH",
            help="directory for storing cached data (will be created if necessary, but parent directory must exist) (default: %(default)s)")

    ap.set_defaults(**Defaults())

    return ap
