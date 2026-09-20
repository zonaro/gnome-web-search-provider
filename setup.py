#!/usr/bin/env python3
"""Installer for the GNOME web search provider.

Install system-wide (root required for /usr/local paths):

    sudo pip install .
    sudo glib-compile-schemas /usr/local/share/glib-2.0/schemas/

The second command registers the GSettings schema so the provider and the
configuration app can use it.
"""

from setuptools import find_packages, setup

setup(
    name="gnome-web-search-provider",
    version="1.0.0",
    description=(
        "GNOME Shell web search provider with multiple configurable "
        "search engines (Google, Bing, DuckDuckGo, Brave, Startpage, ...)"
    ),
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/zonaro/gnome-web-search-provider",
    license="MIT",
    packages=find_packages("src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "gnome-web-search-provider = gnome_web_search_provider:main",
            "gnome-web-search-provider-config = gnome_web_search_provider.config_app:main",
        ],
    },
    data_files=[
        (
            "share/glib-2.0/schemas",
            ["data/org.gnome.WebSearch.SearchProvider.gschema.xml"],
        ),
        (
            "share/applications",
            [
                "data/org.gnome.WebSearch.SearchProvider.desktop",
                "data/org.gnome.WebSearch.SearchProviderConfig.desktop",
            ],
        ),
        (
            "share/gnome-shell/search-providers",
            ["data/org.gnome.WebSearch.SearchProvider.ini"],
        ),
        (
            "share/dbus-1/services",
            ["data/org.gnome.WebSearch.SearchProvider.service"],
        ),
    ],
    python_requires=">=3.8",
    install_requires=[
        "dasbus>=1.7",
        "PyGObject>=3.36",
    ],
    classifiers=[
        "Environment :: Plugins",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Topic :: Desktop Environment :: Gnome",
    ],
)