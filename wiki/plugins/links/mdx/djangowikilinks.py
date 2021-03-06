#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Wikipath Extension for Python-Markdown
======================================

Converts [Link Name](wiki:ArticleName) to relative links pointing to article.  Requires Python-Markdown 2.0+

Basic usage:

    >>> import markdown
    >>> text = "Some text with a [Link Name](wiki:ArticleName)."
    >>> html = markdown.markdown(text, ['wikipath(base_url="/wiki/view/")'])
    >>> html
    '<p>Some text with a <a class="wikipath" href="/wiki/view/ArticleName/">Link Name</a>.</p>'

Dependencies:
* [Python 2.3+](http://python.org)
* [Markdown 2.0+](http://www.freewisdom.org/projects/python-markdown/)
'''
from __future__ import absolute_import, unicode_literals

from os import path as os_path

import markdown
from wiki import models

try:
    # Markdown 2.1.0 changed from 2.0.3. We try importing the new version first,
    # but import the 2.0.3 version if it fails
    from markdown.util import etree  # @UnusedImport
except ImportError:
    from markdown import etree  # @UnresolvedImport @Reimport @UnusedImport


class WikiPathExtension(markdown.Extension):

    def __init__(self, configs):
        # set extension defaults
        self.config = {
            'base_url': [
                '/',
                'String to append to beginning of URL.'],
            'html_class': [
                'wikipath',
                'CSS hook. Leave blank for none.'],
            'default_level': [
                2,
                'The level that most articles are created at. Relative links will tend to start at that level.']}

        # Override defaults with user settings
        for key, value in configs:
            # self.config[key][0] = value
            self.setConfig(key, value)

    def extendMarkdown(self, md, md_globals):
        self.md = md

        # append to end of inline patterns
        WIKI_RE_1 = r'\[(?P<linkTitle>[^\]]*?)\]\(wiki:(?P<wikiTitle>[^\)]*?)\)'
        wikiPathPattern1 = WikiPath(WIKI_RE_1, self.config, False, markdown_instance=md)
        wikiPathPattern1.md = md
        md.inlinePatterns.add('djangowikipath', wikiPathPattern1, "<reference")

        WIKI_RE_2 = r'\[\[(?P<wikiTitle>[^\]]*?)\]\]'
        wikiPathPattern2 = WikiPath(WIKI_RE_2, self.config, True, markdown_instance=md)
        wikiPathPattern2.md = md
        md.inlinePatterns.add('djangowikipathshort', wikiPathPattern2, "<reference")

class WikiPath(markdown.inlinepatterns.Pattern):

    def __init__(self, pattern, config, shorthand, **kwargs):
        markdown.inlinepatterns.Pattern.__init__(self, pattern, **kwargs)
        self.config = config
        self.shorthand = shorthand

    def handleMatch(self, m):
        article_title = m.group('wikiTitle')
        absolute = False
        if article_title.startswith("/"):
            absolute = True
        article_title = article_title.strip("/")

        revisions = models.ArticleRevision.objects.filter(title = article_title)
        if len(revisions) != 0:
            revision = revisions[0]
            slug = ""
            parents = models.URLPath.objects.filter(article_id = revision.article_id)
            while len(parents) != 0 and parents[0].slug != None:
                slug = parents[0].slug + "/" + slug
                parents = models.URLPath.objects.filter(id = parents[0].parent_id)
            path = self.config['base_url'][0] + slug
        else:
            path = ""

        a = etree.Element('a')

        label = ""
        if not self.shorthand:
            label = m.group('linkTitle')
        if label == "":
            label = article_title

        if path == "":
            a.set('class', self.config['html_class'][0] + " linknotfound")
            a.set('href', path)
            a.text = label
        else:
            a.set('href', path)
            a.set('class', self.config['html_class'][0])
            a.text = label

        return a

    def _getMeta(self):
        """ Return meta data or config data. """
        base_url = self.config['base_url'][0]
        html_class = self.config['html_class'][0]
        if hasattr(self.md, 'Meta'):
            if 'wiki_base_url' in self.md.Meta:
                base_url = self.md.Meta['wiki_base_url'][0]
            if 'wiki_html_class' in self.md.Meta:
                html_class = self.md.Meta['wiki_html_class'][0]
        return base_url, html_class


def makeExtension(configs=None):
    return WikiPathExtension(configs=configs)
