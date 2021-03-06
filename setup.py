from setuptools import setup, find_packages
setup(name='easydl',
      version='0.0.1',
      description='"init repo"',
      url='https://github.com/thuml/easydl',
      license='MIT',
      packages=['easydl','easydl.tf', 'easydl.common', 'easydl.pytorch'],
      install_requires=['tensorflow','tensorlayer','numpy','scikit-image','tensorpack','scipy','matplotlib','pathlib2','pytreebank'],
      entry_points={
        'console_scripts': [
                'runTask= easydl:runTask'],
    },
      zip_safe=False)
